"""Approving or rejecting what an agent proposed. Approval runs the change through the shared
action layer as the approving person, so their access rules apply at that moment."""

from datetime import timedelta

from fastapi import HTTPException, status
from sqlmodel import Session, col, select

from app.core.config import settings
from app.models import (
    ActivityCreate,
    AgentProposal,
    Deal,
    DealStatus,
    ProposalStatus,
    Role,
    User,
    utcnow,
)
from app.services import actions

PIPELINE = "pipeline_agent"  # AgentProposal.source for the pipeline agent's suggestions


def can_decide(user: User, proposal: AgentProposal) -> bool:
    return proposal.user_id == user.id or user.role in (Role.owner, Role.admin)


def _apply(session: Session, p: AgentProposal, user: User) -> None:
    via = p.source
    params = p.params
    if p.action == "move_stage":
        actions.update_deal(session, user, p.deal_id, {"stage_id": params["stage_id"]}, via=via)  # type: ignore[arg-type]
    elif p.action == "update_deal":
        actions.update_deal(session, user, p.deal_id, params, via=via)  # type: ignore[arg-type]
    elif p.action == "mark_won":
        actions.mark_won(session, user, p.deal_id, via=via)  # type: ignore[arg-type]
    elif p.action == "mark_lost":
        actions.mark_lost(
            session,
            user,
            p.deal_id,  # type: ignore[arg-type]
            params["lost_reason_id"],
            params.get("note"),
            via=via,
        )
    elif p.action == "log_activity":
        body = ActivityCreate.model_validate({**params, "owner_id": p.user_id})
        actions.create_activity(session, user, body, via=via)
    elif p.action == "complete_activity":
        actions.update_activity(session, user, params["activity_id"], {"done": True})
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown action {p.action}")


def _locked(session: Session, proposal_id: int) -> AgentProposal | None:
    """The proposal, read fresh and locked until this transaction ends."""
    stmt = (
        select(AgentProposal)
        .where(AgentProposal.id == proposal_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return session.exec(stmt).first()


def decide(session: Session, user: User, proposal_id: int, approve: bool) -> AgentProposal:
    """Approve or reject a proposal.

    The proposal's row stays locked until the decision is committed, so a second click (or a
    second admin) waits and then finds it decided, instead of applying the change twice. An
    approved change and the proposal's new status are committed together.
    """
    proposal = _locked(session, proposal_id)
    if proposal is None or not can_decide(user, proposal):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    _check_pending(proposal)
    proposal.decided_by_id = user.id
    proposal.decided_at = utcnow()
    proposal.status = ProposalStatus.approved if approve else ProposalStatus.rejected
    session.add(proposal)
    if approve:
        try:
            _apply(session, proposal, user)  # its commit saves the proposal's status too
        except HTTPException as exc:
            # e.g. the deal was closed or reassigned since the proposal was made
            session.rollback()  # drops the half-made change and releases the lock
            proposal = _locked(session, proposal_id)
            assert proposal is not None
            _check_pending(proposal)  # decided by someone else in the meantime
            proposal.decided_by_id = user.id
            proposal.decided_at = utcnow()
            proposal.status = ProposalStatus.failed
            proposal.error = str(exc.detail)
            session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal


def _check_pending(proposal: AgentProposal) -> None:
    if proposal.status != ProposalStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Proposal is already {proposal.status}")


def expire_stale_suggestions(session: Session) -> int:
    """Expire the pipeline agent's suggestions that are waiting but no longer useful, and
    commit; returns how many.

    The agent doesn't review a deal again while a suggestion for it is waiting, so one that
    nobody answers would keep that deal out of every review. A suggestion expires when:
    - nobody decided on it within PIPELINE_SUGGESTION_DAYS, so the deal gets a fresh look;
    - its deal was closed, so it no longer applies;
    - its deal now belongs to someone else, who wouldn't see it (and gets their own review).
    Suggestions someone is deciding on right now are left alone (their rows are locked).
    """
    now = utcnow()
    days = settings.PIPELINE_SUGGESTION_DAYS
    too_old = now - timedelta(days=days)
    rows = session.exec(
        select(AgentProposal, Deal)
        .join(Deal, col(Deal.id) == AgentProposal.deal_id, isouter=True)
        .where(AgentProposal.source == PIPELINE, AgentProposal.status == ProposalStatus.pending)
        .with_for_update(of=AgentProposal, skip_locked=True)
    ).all()
    expired = 0
    for proposal, deal in rows:
        if deal is None:  # deleted for good (the trash withdraws them on delete already)
            reason = "The deal no longer exists"
        elif deal.status != DealStatus.open:
            reason = f"The deal was marked {deal.status.value}, so this no longer applies"
        elif deal.owner_id != proposal.user_id:
            reason = "The deal now belongs to someone else, so this was withdrawn"
        elif proposal.created_at < too_old:
            reason = f"Nobody decided on this within {days} days, so it expired"
        else:
            continue
        proposal.status = ProposalStatus.expired
        proposal.error = reason
        proposal.decided_at = now
        session.add(proposal)
        expired += 1
    session.commit()
    return expired
