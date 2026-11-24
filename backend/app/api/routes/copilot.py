import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.agent import copilot, turns
from app.agent.proposals import decide
from app.api.access import sees_all
from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.core.config import settings
from app.models import (
    AgentConversation,
    AgentProposal,
    AgentProposalPublic,
    AgentRun,
    AgentRunPublic,
    ChatItem,
    ConversationSummary,
    ConversationView,
    CopilotMessageIn,
    Deal,
    NamedRef,
    ProposalStatus,
    Role,
    TurnFailure,
    User,
    utcnow,
)
from app.services.budgets import copilot_block_reason, pipeline_block_reason

log = logging.getLogger(__name__)
router = APIRouter(tags=["copilot"])

ClientDep = Annotated[copilot.MessagesClient | None, Depends(copilot.get_client)]


def _proposals_public(session: Session, rows: list[AgentProposal]) -> list[AgentProposalPublic]:
    deal_ids = {p.deal_id for p in rows if p.deal_id}
    titles = (
        {d.id: d.title for d in session.exec(select(Deal).where(col(Deal.id).in_(deal_ids)))}
        if deal_ids
        else {}
    )
    out = []
    for p in rows:
        pub = AgentProposalPublic.model_validate(p)
        if p.deal_id in titles:
            pub.deal = NamedRef(id=p.deal_id, name=titles[p.deal_id])  # type: ignore[arg-type]
        else:
            pub.deal_id = None  # deleted: no link while it's in the trash
        out.append(pub)
    return out


_STEP_LABELS = {
    "search_deals": "Searched deals",
    "get_deal": "Read a deal",
    "search_contacts": "Searched contacts",
    "list_activities": "Checked activities",
    "pipeline_overview": "Checked the pipeline",
    "lost_deals_report": "Looked at lost deals",
}


def _step_label(session: Session, name: str, inp: dict[str, Any], titles: dict[int, str]) -> str:
    if name == "get_deal" and isinstance(inp.get("deal_id"), int) and inp["deal_id"] in titles:
        return f"Read “{titles[inp['deal_id']]}”"
    if name == "search_deals" and inp.get("query"):
        return f"Searched deals for “{inp['query']}”"
    if name == "search_contacts" and inp.get("query"):
        return f"Searched contacts for “{inp['query']}”"
    if name.startswith("propose_"):
        return "Proposed a change"
    return _STEP_LABELS.get(name, name.replace("_", " "))


def _view(session: Session, conv: AgentConversation) -> ConversationView:
    running = conv.turn_started_at is not None and not turns.is_stale(conv)
    # while Copilot works, the message and the steps so far follow the finished turns
    shown = conv.messages + (conv.turn_progress or [] if running else [])
    proposals = session.exec(
        select(AgentProposal)
        .where(AgentProposal.conversation_id == conv.id)
        .order_by(col(AgentProposal.id))
    ).all()
    by_tool_use = {p.tool_use_id: p.id for p in proposals}
    tool_uses = [
        b
        for m in shown
        if m["role"] == "assistant" and isinstance(m["content"], list)
        for b in m["content"]
        if b.get("type") == "tool_use"
    ]
    # tool inputs are model output: only trust well-formed ids
    deal_ids = {
        b["input"].get("deal_id")
        for b in tool_uses
        if b["name"] == "get_deal" and isinstance(b.get("input", {}).get("deal_id"), int)
    }
    titles = (
        {d.id: d.title for d in session.exec(select(Deal).where(col(Deal.id).in_(deal_ids)))}
        if deal_ids
        else {}
    )

    items: list[ChatItem] = []
    for m in shown:
        content = m["content"]
        if m["role"] == "user" and isinstance(content, str):
            items.append(ChatItem(kind="user", text=content))
        elif m["role"] == "assistant" and isinstance(content, str):
            items.append(ChatItem(kind="assistant", text=content))
        elif m["role"] == "assistant":
            for b in content:
                if b.get("type") == "text" and b.get("text", "").strip():
                    items.append(ChatItem(kind="assistant", text=b["text"]))
                elif b.get("type") == "tool_use":
                    items.append(
                        ChatItem(
                            kind="step",
                            text=_step_label(session, b["name"], b.get("input", {}), titles),
                            proposal_id=by_tool_use.get(b["id"]),
                        )
                    )
    failure = None
    if conv.turn_started_at is not None and not running:  # its process died mid-turn
        failure = TurnFailure(message=turns.INTERRUPTED, text=turns.turn_text(conv))
    elif conv.turn_error:
        failure = TurnFailure.model_validate(conv.turn_error)
    return ConversationView(
        id=conv.id,  # type: ignore[arg-type]
        title=conv.title,
        model=conv.model,
        items=items,
        proposals=_proposals_public(session, list(proposals)),
        updated_at=conv.updated_at,
        running=running,
        failure=failure,
    )


def _own_conversation(session: Session, user: User, conv_id: int, lock: bool = False):  # noqa: ANN202
    stmt = select(AgentConversation).where(AgentConversation.id == conv_id)
    if lock:  # one turn at a time per conversation, so appends never interleave
        stmt = stmt.with_for_update()
    conv = session.exec(stmt).first()
    if conv is None or conv.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return conv


class AgentStatus(BaseModel):
    enabled: bool
    review_hour: int  # local hour of the daily pipeline review
    timezone: str
    pipeline_budget_reached: str | None = None  # why reviews are paused, if they are


@router.get("/copilot/status", response_model=AgentStatus)
def copilot_status(session: SessionDep, _: CurrentUser, client: ClientDep) -> AgentStatus:
    return AgentStatus(
        enabled=client is not None,
        review_hour=settings.PIPELINE_REVIEW_HOUR,
        timezone=settings.TIMEZONE,
        pipeline_budget_reached=pipeline_block_reason(session),
    )


def _check_turns_per_person(session: Session, user: User, conv_id: int | None) -> None:
    """At most COPILOT_TURNS_PER_PERSON replies under way per person, across their chats.

    The person's row is locked until the turn is marked as started, so two messages sent at
    once (two tabs) are counted one after the other."""
    session.exec(select(User.id).where(User.id == user.id).with_for_update()).one()
    since = utcnow() - turns.TURN_TIMEOUT  # older markers belong to turns that died
    stmt = select(func.count()).where(
        AgentConversation.user_id == user.id,
        col(AgentConversation.turn_started_at) > since,
    )
    if conv_id is not None:  # this chat's own turn gets its own answer (409) below
        stmt = stmt.where(AgentConversation.id != conv_id)
    if session.exec(stmt).one() >= settings.COPILOT_TURNS_PER_PERSON:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Copilot is already answering you in other chats. Try again when one of them is done.",
        )


def _start_turn(session: Session, user: User, body: CopilotMessageIn) -> AgentConversation:
    """The conversation, marked as answering a message. The marker, not a lock held for the
    whole turn, keeps a second message (another tab, a double send) out until it's done; its
    time also names the turn, so a turn that outlives its time limit can tell it was replaced.
    """
    _check_turns_per_person(session, user, body.conversation_id)
    if body.conversation_id is not None:
        conv = _own_conversation(session, user, body.conversation_id, lock=True)
    else:
        title = " ".join(body.text.split())
        conv = AgentConversation(user_id=user.id, title=title[:80] or "New chat")  # type: ignore[arg-type]
    if conv.turn_started_at is not None:
        if not turns.is_stale(conv):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Copilot is still answering your last message in this chat. Try again when "
                "it's done.",
            )
        # its server process died mid-turn (or the turn is still going, far too slowly):
        # withdraw what it proposed before starting afresh, in the same transaction
        turns.end_failed_turn(
            session,
            conv.id,  # type: ignore[arg-type]
            conv.turn_started_at,
            turns.INTERRUPTED,
            turns.turn_text(conv),
            commit=False,
        )
    conv.turn_started_at = utcnow()
    conv.turn_error = None
    conv.turn_progress = [{"role": "user", "content": body.text.strip()}]  # shown straight away
    session.add(conv)
    session.commit()  # releases the row locks
    session.refresh(conv)
    return conv


@router.post(
    "/copilot/messages",
    response_model=ConversationView,
    status_code=status.HTTP_202_ACCEPTED,
)
def send_message(
    session: SessionDep, user: CurrentUser, client: ClientDep, body: CopilotMessageIn
) -> ConversationView:
    """Send a message to the Copilot. It's answered in the background: the conversation comes
    back with `running` set, and shows each step as it happens when read again
    (GET /copilot/conversations/{id}), until the answer is in or `failure` says why not."""
    if client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Copilot isn't set up on this server yet (ANTHROPIC_API_KEY is missing).",
        )
    if (reason := copilot_block_reason(session, user)) is not None:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, reason)
    conv = _start_turn(session, user, body)
    turns.start(
        conv.id,  # type: ignore[arg-type]
        user.id,  # type: ignore[arg-type]
        body.text.strip(),
        body.deal_id,
        client,
        conv.turn_started_at,  # type: ignore[arg-type]
    )
    session.refresh(conv)
    return _view(session, conv)


@router.get("/copilot/conversations", response_model=list[ConversationSummary])
def list_conversations(session: SessionDep, user: CurrentUser) -> list[ConversationSummary]:
    rows = session.exec(
        select(AgentConversation)
        .where(AgentConversation.user_id == user.id)
        .order_by(col(AgentConversation.updated_at).desc())
        .limit(30)
    ).all()
    return [ConversationSummary(id=c.id, title=c.title, updated_at=c.updated_at) for c in rows]  # type: ignore[arg-type]


@router.get("/copilot/conversations/{conversation_id}", response_model=ConversationView)
def read_conversation(
    session: SessionDep, user: CurrentUser, conversation_id: int
) -> ConversationView:
    return _view(session, _own_conversation(session, user, conversation_id))


@router.get("/proposals", response_model=list[AgentProposalPublic])
def list_proposals(
    session: SessionDep,
    user: CurrentUser,
    proposal_status: ProposalStatus | None = Query(None, alias="status"),
    deal_id: int | None = None,
    everyone: bool = Query(False, description="Admins only: include other people's proposals"),
) -> list[AgentProposalPublic]:
    """Proposals made for this user (admins can ask for everyone's)."""
    stmt = select(AgentProposal)
    if not (everyone and user.role in (Role.owner, Role.admin)):
        stmt = stmt.where(AgentProposal.user_id == user.id)
    if proposal_status is not None:
        stmt = stmt.where(AgentProposal.status == proposal_status)
    if deal_id is not None:
        stmt = stmt.where(AgentProposal.deal_id == deal_id)
    rows = session.exec(stmt.order_by(col(AgentProposal.created_at).desc()).limit(100)).all()
    return _proposals_public(session, list(rows))


@router.get("/agent/runs", response_model=list[AgentRunPublic])
def list_agent_runs(
    session: SessionDep, user: CurrentUser, limit: int = Query(20, ge=1, le=100)
) -> list[AgentRunPublic]:
    """Recent pipeline-agent reviews: agents see reviews of their own deals."""
    stmt = select(AgentRun).order_by(col(AgentRun.created_at).desc()).limit(limit)
    if not sees_all(user):
        stmt = stmt.where(AgentRun.user_id == user.id)
    runs = session.exec(stmt).all()
    run_ids = [r.id for r in runs]
    counts = (
        dict(
            session.exec(
                select(AgentProposal.run_id, func.count())
                .where(col(AgentProposal.run_id).in_(run_ids))
                .group_by(AgentProposal.run_id)
            ).all()
        )
        if run_ids
        else {}
    )
    deal_ids = {r.deal_id for r in runs if r.deal_id}
    titles = (
        {d.id: d.title for d in session.exec(select(Deal).where(col(Deal.id).in_(deal_ids)))}
        if deal_ids
        else {}
    )
    out = []
    for r in runs:
        pub = AgentRunPublic.model_validate(r, update={"proposal_count": counts.get(r.id, 0)})
        if r.deal_id in titles:
            pub.deal = NamedRef(id=r.deal_id, name=titles[r.deal_id])  # type: ignore[arg-type]
        else:
            pub.deal_id = None  # deleted: no link while it's in the trash
        out.append(pub)
    return out


@router.post("/agent/pipeline-review", status_code=status.HTTP_202_ACCEPTED)
def start_pipeline_review(_: AdminUser, client: ClientDep) -> dict[str, bool]:
    """Queue a pipeline review now instead of waiting for the morning run."""
    if client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The pipeline agent isn't set up on this server yet (ANTHROPIC_API_KEY is missing).",
        )
    from app.worker import pipeline_review_task

    try:
        pipeline_review_task.delay()
    except Exception:  # broker down: say so instead of a bare 500
        log.exception("Couldn't queue the pipeline review")
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The background worker isn't reachable, so the review couldn't start.",
        ) from None
    return {"queued": True}


@router.post("/proposals/{proposal_id}/approve", response_model=AgentProposalPublic)
def approve_proposal(
    session: SessionDep, user: CurrentUser, proposal_id: int
) -> AgentProposalPublic:
    """Apply the proposed change as the approving user. A change that no longer applies (the
    deal was closed meanwhile, say) is marked failed with the reason."""
    p = decide(session, user, proposal_id, approve=True)
    return _proposals_public(session, [p])[0]


@router.post("/proposals/{proposal_id}/reject", response_model=AgentProposalPublic)
def reject_proposal(
    session: SessionDep, user: CurrentUser, proposal_id: int
) -> AgentProposalPublic:
    p = decide(session, user, proposal_id, approve=False)
    return _proposals_public(session, [p])[0]
