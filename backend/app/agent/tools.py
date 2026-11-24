"""Tools the Copilot can call.

Read tools run straight away, limited to what the signed-in user can see. Change tools never
change anything: they create an AgentProposal that the person approves or rejects in the UI.
Every tool's input is a Pydantic model; its schema is sent with `strict: true` and the model
re-validates the input before anything runs.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlmodel import Session, col, or_, select

from app.agent.schema import strict_schema
from app.api.access import get_visible, scoped, sees_all
from app.core.time import describe, team_tz
from app.models import (
    Activity,
    ActivityType,
    AgentProposal,
    Company,
    Contact,
    Deal,
    DealEvent,
    DealPublic,
    DealStatus,
    LostReason,
    Pipeline,
    Role,
    Stage,
    User,
    utcnow,
)
from app.services.names import contact_name, user_refs, with_deal_names
from app.services.rotting import AUTO_REMINDER
from app.services.stats import money, open_totals_by_stage, weighted


@dataclass
class ToolContext:
    session: Session
    user: User
    source: str  # who is proposing: "copilot" or "pipeline_agent"
    conversation_id: int | None = None
    run_id: int | None = None
    tool_use_id: str | None = None
    proposals_left: int | None = None  # None: no limit


class ToolError(Exception):
    """Shown to the model as an error result so it can correct itself."""


@dataclass
class Tool:
    name: str
    description: str
    input_model: type[BaseModel]
    run: Callable[[ToolContext, Any], Any]
    proposes_change: bool = False

    def spec(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": strict_schema(self.input_model),
            "strict": True,
        }


def _stage_names(session: Session) -> dict[int, str]:
    return {s.id: s.name for s in session.exec(select(Stage)).all()}  # type: ignore[misc]


def _deal_brief(d: DealPublic, stages: dict[int, str]) -> dict[str, Any]:
    days = (utcnow() - d.stage_changed_at).days
    return {
        "id": d.id,
        "title": d.title,
        "value": f"{d.currency} {d.value}",
        "status": d.status,
        "stage": stages.get(d.stage_id),
        "days_in_stage": days,
        "stalled": d.is_rotting,
        "owner": d.owner.name if d.owner else None,
        "company": d.company.name if d.company else None,
        "contact": d.contact.name if d.contact else None,
        "expected_close_date": d.expected_close_date.isoformat() if d.expected_close_date else None,
    }


def _visible_deal(ctx: ToolContext, deal_id: int) -> Deal:
    try:
        return get_visible(ctx.session, Deal, deal_id, ctx.user)
    except HTTPException:
        raise ToolError(f"Deal {deal_id} doesn't exist or isn't visible to this user") from None


# ---------------------------------------------------------------- read tools


class SearchDeals(BaseModel):
    query: str | None = Field(description="Words in the deal title; null for all deals")
    status: Literal["open", "won", "lost", "any"] = Field(description="Deal status filter")
    stalled_only: bool = Field(description="Only deals flagged as stalled")
    mine_only: bool = Field(description="Only deals owned by the signed-in user")
    limit: int = Field(description="Maximum deals to return, 1-50")


def search_deals(ctx: ToolContext, inp: SearchDeals) -> Any:
    stmt = scoped(select(Deal), Deal, ctx.user)
    if inp.query:
        stmt = stmt.where(col(Deal.title).ilike(f"%{inp.query}%"))
    if inp.status != "any":
        stmt = stmt.where(Deal.status == inp.status)
    if inp.stalled_only:
        stmt = stmt.where(col(Deal.rotting_since).is_not(None))
    if inp.mine_only:
        stmt = stmt.where(Deal.owner_id == ctx.user.id)
    limit = max(1, min(inp.limit, 50))
    rows = ctx.session.exec(stmt.order_by(col(Deal.updated_at).desc()).limit(limit)).all()
    deals = with_deal_names(ctx.session, [DealPublic.model_validate(d) for d in rows])
    stages = _stage_names(ctx.session)
    return {"deals": [_deal_brief(d, stages) for d in deals]}


class GetDeal(BaseModel):
    deal_id: int = Field(description="The deal's id")


def get_deal(ctx: ToolContext, inp: GetDeal) -> Any:
    deal = _visible_deal(ctx, inp.deal_id)
    d = with_deal_names(ctx.session, [DealPublic.model_validate(deal)])[0]
    stages = _stage_names(ctx.session)
    events = ctx.session.exec(
        select(DealEvent).where(DealEvent.deal_id == deal.id).order_by(col(DealEvent.created_at))
    ).all()
    activities = ctx.session.exec(
        select(Activity).where(Activity.deal_id == deal.id).order_by(col(Activity.created_at))
    ).all()
    names = user_refs(ctx.session, [e.actor_id for e in events] + [a.owner_id for a in activities])

    history: list[tuple[datetime, str]] = []
    for e in events:
        who = names[e.actor_id].name if e.actor_id in names else "Dealflow"
        detail = dict(e.data)
        for key in ("stage_id", "from_stage_id", "to_stage_id"):
            if key in detail:
                detail[key.replace("_id", "")] = stages.get(detail.pop(key))
        history.append((e.created_at, f"{who}: {e.kind} {json.dumps(detail, default=str)}"))
    for a in activities:
        state = "done" if a.done else f"open, due {a.due_at:%Y-%m-%d %H:%M}" if a.due_at else "open"
        who = names[a.owner_id].name if a.owner_id in names else "?"
        if a.via == AUTO_REMINDER:
            # Dealflow's own generic nudge: say so, or it reads as a planned next step
            text = f"Dealflow (automatic stalled-deal reminder, not a plan): task #{a.id} ({state})"
        else:
            text = f"{who}: {a.type} #{a.id} ({state}) {a.subject!r}"
            if a.via:
                text += f" [added via {a.via.replace('_', ' ')}]"
            if a.body:
                text += f": {a.body[:500]!r}"
        history.append((a.created_at, text))
    history.sort()

    brief = _deal_brief(d, stages)
    brief.update(
        stage_id=d.stage_id,
        pipeline_id=d.pipeline_id,
        lost_reason_id=d.lost_reason_id,
        lost_note=d.lost_note,
        custom_fields=d.custom_fields,
        created=d.created_at.date().isoformat(),
        history=[f"{at:%Y-%m-%d} {line}" for at, line in history[-40:]],
    )
    return brief


class SearchContacts(BaseModel):
    query: str = Field(description="Name, email, phone or company name to look for")


def search_contacts(ctx: ToolContext, inp: SearchContacts) -> Any:
    like = f"%{inp.query}%"
    stmt = (
        scoped(select(Contact, Company), Contact, ctx.user)
        .join(Company, col(Company.id) == Contact.company_id, isouter=True)
        .where(
            or_(
                col(Contact.first_name).ilike(like),
                col(Contact.last_name).ilike(like),
                col(Contact.email).ilike(like),
                col(Contact.phone).ilike(like),
                col(Company.name).ilike(like),
            )
        )
        .limit(20)
    )
    return {
        "contacts": [
            {
                "id": c.id,
                "name": contact_name(c),
                "job_title": c.job_title,
                "email": c.email,
                "phone": c.phone,
                "company": co.name if co else None,
                "company_id": c.company_id,
            }
            for c, co in ctx.session.exec(stmt).all()
        ]
    }


class ListActivities(BaseModel):
    deal_id: int | None = Field(description="Only activities on this deal; null for all")
    open_only: bool = Field(description="Only activities not yet done")
    overdue_only: bool = Field(description="Only open activities past their due time")
    mine_only: bool = Field(description="Only the signed-in user's activities")


def list_activities(ctx: ToolContext, inp: ListActivities) -> Any:
    stmt = scoped(select(Activity), Activity, ctx.user)
    if inp.deal_id is not None:
        stmt = stmt.where(Activity.deal_id == inp.deal_id)
    if inp.open_only or inp.overdue_only:
        stmt = stmt.where(col(Activity.done).is_(False))
    if inp.overdue_only:
        stmt = stmt.where(col(Activity.due_at) < utcnow())
    if inp.mine_only:
        stmt = stmt.where(Activity.owner_id == ctx.user.id)
    rows = ctx.session.exec(stmt.order_by(col(Activity.due_at), col(Activity.id)).limit(50)).all()
    return {
        "activities": [
            {
                "id": a.id,
                "type": a.type,
                "subject": a.subject,
                "done": a.done,
                "due_at": a.due_at.isoformat() if a.due_at else None,
                "deal_id": a.deal_id,
                "contact_id": a.contact_id,
            }
            for a in rows
        ]
    }


class PipelineOverview(BaseModel):
    pass


def pipeline_overview(ctx: ToolContext, _: PipelineOverview) -> Any:
    """Pipelines, stage ids, totals and lost reasons: the reference data change tools need."""
    pipelines = []
    for p in ctx.session.exec(select(Pipeline).order_by(col(Pipeline.id))).all():
        totals = open_totals_by_stage(ctx.session, ctx.user, p.id)  # type: ignore[arg-type]
        stages = []
        for s in p.stages:
            t = totals.get(s.id)  # type: ignore[arg-type]
            total = t.total if t else Decimal(0)
            stages.append(
                {
                    "stage_id": s.id,
                    "name": s.name,
                    "win_probability": s.probability,
                    "open_deals": t.count if t else 0,
                    "stalled_deals": t.rotting if t else 0,
                    "open_value": str(money(total)),
                    "weighted_value": str(weighted(total, s.probability)),
                }
            )
        pipelines.append(
            {
                "pipeline_id": p.id,
                "name": p.name,
                "stall_after_days": p.rotting_days,
                "stages": stages,
            }
        )
    reasons = ctx.session.exec(select(LostReason).where(col(LostReason.is_active).is_(True))).all()
    return {
        "visibility": "whole team" if sees_all(ctx.user) else "only this user's own records",
        "pipelines": pipelines,
        "lost_reasons": [{"lost_reason_id": r.id, "label": r.label} for r in reasons],
    }


class LostDealsReport(BaseModel):
    days: int = Field(description="Look back this many days, e.g. 90")


def lost_deals_report(ctx: ToolContext, inp: LostDealsReport) -> Any:
    since = utcnow() - timedelta(days=max(1, min(inp.days, 3650)))
    rows = ctx.session.exec(
        scoped(select(LostReason.label, func.count(), func.sum(Deal.value)), Deal, ctx.user)
        .join(LostReason, col(LostReason.id) == Deal.lost_reason_id)
        .where(Deal.status == DealStatus.lost, col(Deal.closed_at) >= since)
        .group_by(LostReason.label)
    ).all()
    notes = ctx.session.exec(
        scoped(select(Deal.title, Deal.lost_note), Deal, ctx.user)
        .where(Deal.status == DealStatus.lost, col(Deal.closed_at) >= since)
        .where(col(Deal.lost_note).is_not(None))
        .limit(30)
    ).all()
    return {
        "since": since.date().isoformat(),
        "by_reason": [{"reason": r, "deals": n, "value": str(money(v))} for r, n, v in rows],
        "notes": [{"deal": t, "note": n} for t, n in notes],
    }


# ---------------------------------------------------------------- change tools (proposals)


def _propose(
    ctx: ToolContext,
    action: str,
    params: dict[str, Any],
    summary: str,
    rationale: str,
    deal: Deal | None = None,
    counts: bool = True,
) -> Any:
    """Create an approval card. `counts=False` for housekeeping (closing Dealflow's own
    stalled-deal reminder), which a review may do on top of its limit of real changes."""
    if ctx.user.role == Role.viewer:
        raise ToolError("This user is a viewer and can't change anything; just answer in words.")
    if counts and ctx.proposals_left is not None and ctx.proposals_left <= 0:
        raise ToolError("You've reached the maximum number of proposals for this review.")
    proposal = AgentProposal(
        source=ctx.source,
        conversation_id=ctx.conversation_id,
        run_id=ctx.run_id,
        tool_use_id=ctx.tool_use_id,
        user_id=ctx.user.id,  # type: ignore[arg-type]
        deal_id=deal.id if deal else None,
        action=action,
        params=params,
        summary=summary[:500],
        rationale=rationale[:2000] or None,
    )
    ctx.session.add(proposal)
    ctx.session.flush()
    result = {
        "proposal_id": proposal.id,
        "status": "pending approval",
        "summary": proposal.summary,
        "note": "Nothing has changed yet. The user sees this as a card and approves or rejects it.",
    }
    if not counts:
        result["counts_toward_limit"] = False
    return result


def _open_deal(ctx: ToolContext, deal_id: int) -> Deal:
    deal = _visible_deal(ctx, deal_id)
    if deal.status != DealStatus.open:
        raise ToolError(f"Deal {deal_id} is {deal.status.value}; it has to be reopened first")
    return deal


class MoveDealStage(BaseModel):
    deal_id: int
    stage_id: int = Field(description="Target stage id from pipeline_overview")
    reason: str = Field(description="One sentence on why, shown to the user")


def propose_move_stage(ctx: ToolContext, inp: MoveDealStage) -> Any:
    deal = _open_deal(ctx, inp.deal_id)
    stage = ctx.session.get(Stage, inp.stage_id)
    if stage is None:
        raise ToolError(f"Stage {inp.stage_id} doesn't exist; check pipeline_overview")
    if stage.id == deal.stage_id:
        raise ToolError("The deal is already in that stage")
    current = ctx.session.get(Stage, deal.stage_id)
    summary = f"Move “{deal.title}” from {current.name if current else '?'} to {stage.name}"
    return _propose(ctx, "move_stage", {"stage_id": stage.id}, summary, inp.reason, deal)


class UpdateDeal(BaseModel):
    deal_id: int
    title: str | None = Field(description="New title, or null to keep it")
    value: str | None = Field(description="New value as a decimal string like '250000.00', or null")
    expected_close_date: date | None = Field(description="YYYY-MM-DD, or null to keep it")
    reason: str = Field(description="One sentence on why, shown to the user")


def propose_update_deal(ctx: ToolContext, inp: UpdateDeal) -> Any:
    deal = _visible_deal(ctx, inp.deal_id)
    params: dict[str, Any] = {}
    parts = []
    if inp.title is not None and inp.title.strip() and inp.title != deal.title:
        params["title"] = inp.title.strip()[:255]
        parts.append(f"title to “{params['title']}”")
    if inp.value is not None:
        try:
            value = Decimal(inp.value).quantize(Decimal("0.01"))
        except ArithmeticError:
            raise ToolError("value must be a decimal string like '250000.00'") from None
        if value < 0:
            raise ToolError("value can't be negative")
        if value != deal.value:
            params["value"] = str(value)
            parts.append(f"value to {deal.currency} {value:,}")
    if inp.expected_close_date is not None and inp.expected_close_date != deal.expected_close_date:
        params["expected_close_date"] = inp.expected_close_date.isoformat()
        parts.append(f"expected close to {inp.expected_close_date:%d %b %Y}")
    if not params:
        raise ToolError("Nothing would change; pass at least one new value")
    summary = f"Change “{deal.title}”: " + ", ".join(parts)
    return _propose(ctx, "update_deal", params, summary, inp.reason, deal)


class LogActivity(BaseModel):
    deal_id: int | None = Field(description="Deal to attach it to, or null")
    contact_id: int | None = Field(description="Contact to attach it to, or null")
    type: ActivityType
    subject: str = Field(description="Short title, e.g. 'Send revised quote'")
    body: str | None = Field(description="Details, or null")
    due_at: datetime | None = Field(description="ISO 8601 due time for tasks/meetings, or null")
    done: bool = Field(description="True when recording something that already happened")
    reason: str = Field(description="One sentence on why, shown to the user")


def propose_log_activity(ctx: ToolContext, inp: LogActivity) -> Any:
    deal = _visible_deal(ctx, inp.deal_id) if inp.deal_id is not None else None
    contact_id = inp.contact_id
    if contact_id is not None:
        try:
            get_visible(ctx.session, Contact, contact_id, ctx.user)
        except HTTPException:
            raise ToolError(f"Contact {contact_id} isn't visible to this user") from None
    if deal and contact_id is None:
        contact_id = deal.contact_id
    subject = inp.subject.strip()[:255]
    if not subject:
        raise ToolError("subject can't be empty")
    due_at = inp.due_at
    if due_at is not None and due_at.tzinfo is None:  # a bare time means the team's local time
        due_at = due_at.replace(tzinfo=team_tz())
    params = {
        "type": inp.type.value,
        "subject": subject,
        "body": inp.body,
        "due_at": due_at.isoformat() if due_at else None,
        "done": inp.done,
        "deal_id": deal.id if deal else None,
        "contact_id": contact_id,
        "company_id": deal.company_id if deal else None,
    }
    verb = "Log" if inp.done else "Add"
    target = f" on “{deal.title}”" if deal else ""
    due = f", due {describe(due_at)}" if due_at and not inp.done else ""
    summary = f"{verb} {inp.type.value}{target}: {subject}{due}"
    return _propose(ctx, "log_activity", params, summary, inp.reason, deal)


class CompleteActivity(BaseModel):
    activity_id: int
    reason: str = Field(description="One sentence on why, shown to the user")


def propose_complete_activity(ctx: ToolContext, inp: CompleteActivity) -> Any:
    try:
        activity = get_visible(ctx.session, Activity, inp.activity_id, ctx.user)
    except HTTPException:
        raise ToolError(f"Activity {inp.activity_id} isn't visible to this user") from None
    if activity.done:
        raise ToolError("That activity is already done")
    deal = ctx.session.get(Deal, activity.deal_id) if activity.deal_id else None
    summary = f"Mark {activity.type.value} “{activity.subject}” as done"
    return _propose(
        ctx,
        "complete_activity",
        {"activity_id": activity.id},
        summary,
        inp.reason,
        deal,
        # closing Dealflow's generic reminder is housekeeping, not one of the review's changes
        counts=activity.via != AUTO_REMINDER,
    )


class MarkWon(BaseModel):
    deal_id: int
    reason: str = Field(description="One sentence on why, shown to the user")


def propose_mark_won(ctx: ToolContext, inp: MarkWon) -> Any:
    deal = _open_deal(ctx, inp.deal_id)
    summary = f"Mark “{deal.title}” as won ({deal.currency} {deal.value:,})"
    return _propose(ctx, "mark_won", {}, summary, inp.reason, deal)


class MarkLost(BaseModel):
    deal_id: int
    lost_reason_id: int = Field(description="Id from pipeline_overview's lost_reasons")
    note: str | None = Field(description="Short note on what happened, or null")
    reason: str = Field(description="One sentence on why, shown to the user")


def propose_mark_lost(ctx: ToolContext, inp: MarkLost) -> Any:
    deal = _open_deal(ctx, inp.deal_id)
    reason = ctx.session.get(LostReason, inp.lost_reason_id)
    if reason is None or not reason.is_active:
        raise ToolError("Unknown lost reason; use an id from pipeline_overview")
    summary = f"Mark “{deal.title}” as lost: {reason.label}"
    params = {"lost_reason_id": reason.id, "note": inp.note}
    return _propose(ctx, "mark_lost", params, summary, inp.reason, deal)


TOOLS: list[Tool] = [
    Tool(
        "search_deals",
        "Find deals by title words, status, stalled flag or owner. Returns ids, stage, value, "
        "owner, company, contact and days in the current stage.",
        SearchDeals,
        search_deals,
    ),
    Tool(
        "get_deal",
        "Full detail for one deal, including its history of changes, notes, calls, meetings "
        "and tasks. Use before proposing changes to a deal.",
        GetDeal,
        get_deal,
    ),
    Tool(
        "search_contacts",
        "Find contacts by name, email, phone or company.",
        SearchContacts,
        search_contacts,
    ),
    Tool(
        "list_activities",
        "List tasks, calls, meetings and notes, e.g. overdue tasks or open tasks on a deal.",
        ListActivities,
        list_activities,
    ),
    Tool(
        "pipeline_overview",
        "Pipelines with stage ids, win probabilities, open/stalled counts and values, plus the "
        "lost reasons with ids. Call it for any stage or lost-reason id you need.",
        PipelineOverview,
        pipeline_overview,
    ),
    Tool(
        "lost_deals_report",
        "Why deals were lost recently: counts and value per reason, plus the notes people left.",
        LostDealsReport,
        lost_deals_report,
    ),
    Tool(
        "propose_move_stage",
        "Propose moving an open deal to another stage. Creates an approval card; changes nothing "
        "until the user approves.",
        MoveDealStage,
        propose_move_stage,
        proposes_change=True,
    ),
    Tool(
        "propose_update_deal",
        "Propose changing a deal's title, value or expected close date. Creates an approval card.",
        UpdateDeal,
        propose_update_deal,
        proposes_change=True,
    ),
    Tool(
        "propose_log_activity",
        "Propose adding a note, call, meeting, email or task, e.g. a follow-up task with a due "
        "time or a record of a call that happened. Creates an approval card.",
        LogActivity,
        propose_log_activity,
        proposes_change=True,
    ),
    Tool(
        "propose_complete_activity",
        "Propose marking a task, call or meeting as done. Creates an approval card.",
        CompleteActivity,
        propose_complete_activity,
        proposes_change=True,
    ),
    Tool(
        "propose_mark_won",
        "Propose marking an open deal as won. Creates an approval card.",
        MarkWon,
        propose_mark_won,
        proposes_change=True,
    ),
    Tool(
        "propose_mark_lost",
        "Propose marking an open deal as lost with a reason. Creates an approval card.",
        MarkLost,
        propose_mark_lost,
        proposes_change=True,
    ),
]

TOOLS_BY_NAME = {t.name: t for t in TOOLS}
# Fixed order and content: changing the tool list mid-conversation would invalidate the
# conversation's earlier thinking blocks.
TOOL_SPECS = [t.spec() for t in TOOLS]
