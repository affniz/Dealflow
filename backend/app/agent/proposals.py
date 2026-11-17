"""Approving or rejecting what an agent proposed. Approval runs the change through the shared
action layer as the approving person, so their access rules apply at that moment."""

from fastapi import HTTPException, status
from sqlmodel import Session

from app.models import ActivityCreate, AgentProposal, ProposalStatus, Role, User, utcnow
from app.services import actions


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
            p.deal_id,
            params["lost_reason_id"],
            params.get("note"),
            via=via,  # type: ignore[arg-type]
        )
    elif p.action == "log_activity":
        body = ActivityCreate.model_validate({**params, "owner_id": p.user_id})
        actions.create_activity(session, user, body, via=via)
    elif p.action == "complete_activity":
        actions.update_activity(session, user, params["activity_id"], {"done": True})
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown action {p.action}")


def decide(session: Session, user: User, proposal: AgentProposal, approve: bool) -> AgentProposal:
    if not can_decide(user, proposal):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Proposal not found")
    if proposal.status != ProposalStatus.pending:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Proposal is already {proposal.status}")
    proposal.decided_by_id = user.id
    proposal.decided_at = utcnow()
    if not approve:
        proposal.status = ProposalStatus.rejected
    else:
        try:
            _apply(session, proposal, user)  # commits on success
            proposal.status = ProposalStatus.approved
        except HTTPException as exc:
            # e.g. the deal was closed or reassigned since the proposal was made
            session.rollback()
            session.refresh(proposal)
            proposal.decided_by_id = user.id
            proposal.decided_at = utcnow()
            proposal.status = ProposalStatus.failed
            proposal.error = str(exc.detail)
    session.add(proposal)
    session.commit()
    session.refresh(proposal)
    return proposal
