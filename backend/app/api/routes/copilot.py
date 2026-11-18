import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, col, select

from app.agent import copilot
from app.agent.proposals import can_decide, decide
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
    User,
)

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
    proposals = session.exec(
        select(AgentProposal)
        .where(AgentProposal.conversation_id == conv.id)
        .order_by(col(AgentProposal.id))
    ).all()
    by_tool_use = {p.tool_use_id: p.id for p in proposals}
    tool_uses = [
        b
        for m in conv.messages
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
    for m in conv.messages:
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
    return ConversationView(
        id=conv.id,  # type: ignore[arg-type]
        title=conv.title,
        items=items,
        proposals=_proposals_public(session, list(proposals)),
        updated_at=conv.updated_at,
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


@router.get("/copilot/status", response_model=AgentStatus)
def copilot_status(_: CurrentUser, client: ClientDep) -> AgentStatus:
    return AgentStatus(
        enabled=client is not None,
        review_hour=settings.PIPELINE_REVIEW_HOUR,
        timezone=settings.TIMEZONE,
    )


@router.post("/copilot/messages", response_model=ConversationView)
def send_message(
    session: SessionDep, user: CurrentUser, client: ClientDep, body: CopilotMessageIn
) -> ConversationView:
    """Send a message to the Copilot and get the updated conversation back."""
    if client is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Copilot isn't set up on this server yet (ANTHROPIC_API_KEY is missing).",
        )
    if body.conversation_id is not None:
        conv = _own_conversation(session, user, body.conversation_id, lock=True)
    else:
        title = " ".join(body.text.split())
        conv = AgentConversation(user_id=user.id, title=title[:80] or "New chat")  # type: ignore[arg-type]
        session.add(conv)
        session.commit()
        session.refresh(conv)
        conv = _own_conversation(session, user, conv.id, lock=True)  # type: ignore[arg-type]

    import anthropic

    try:
        copilot.run_turn(session, client, user, conv, body.text.strip(), body.deal_id)
    except anthropic.APIError as exc:
        session.rollback()
        log.warning("Copilot call failed: %s", exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Copilot couldn't reach Claude just now. Try again."
        ) from None
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


def _proposal(session: Session, user: User, proposal_id: int) -> AgentProposal:
    p = session.get(AgentProposal, proposal_id)
    if p is None or not can_decide(user, p):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    return p


@router.post("/proposals/{proposal_id}/approve", response_model=AgentProposalPublic)
def approve_proposal(
    session: SessionDep, user: CurrentUser, proposal_id: int
) -> AgentProposalPublic:
    """Apply the proposed change as the approving user. A change that no longer applies (the
    deal was closed meanwhile, say) is marked failed with the reason."""
    p = decide(session, user, _proposal(session, user, proposal_id), approve=True)
    return _proposals_public(session, [p])[0]


@router.post("/proposals/{proposal_id}/reject", response_model=AgentProposalPublic)
def reject_proposal(
    session: SessionDep, user: CurrentUser, proposal_id: int
) -> AgentProposalPublic:
    p = decide(session, user, _proposal(session, user, proposal_id), approve=False)
    return _proposals_public(session, [p])[0]
