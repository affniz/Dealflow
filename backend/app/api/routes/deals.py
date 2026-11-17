from fastapi import APIRouter, Query, Response, status
from sqlmodel import col, select

from app.api.access import (
    get_visible,
    paginate,
    scoped,
)
from app.api.deps import CurrentUser, SessionDep, WriterUser
from app.models import (
    Activity,
    ActivityPublic,
    AgentProposal,
    Deal,
    DealCreate,
    DealEvent,
    DealEventPublic,
    DealLost,
    DealPublic,
    DealStatus,
    DealUpdate,
    Page,
    ProposalStatus,
    TimelineItem,
)
from app.services import actions
from app.services.names import deal_public, user_refs, with_deal_names

router = APIRouter(prefix="/deals", tags=["deals"])


@router.get("", response_model=Page[DealPublic])
def list_deals(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(None, description="Search title"),
    pipeline_id: int | None = None,
    stage_id: int | None = None,
    deal_status: DealStatus | None = Query(None, alias="status"),
    contact_id: int | None = None,
    company_id: int | None = None,
    rotting: bool | None = Query(None, description="Only rotting (true) or fresh (false) deals"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Page[DealPublic]:
    stmt = scoped(select(Deal), Deal, user)
    if rotting is not None:
        flag = col(Deal.rotting_since)
        stmt = stmt.where(flag.is_not(None) if rotting else flag.is_(None))
    if q:
        stmt = stmt.where(col(Deal.title).ilike(f"%{q}%"))
    filters = {
        Deal.pipeline_id: pipeline_id,
        Deal.stage_id: stage_id,
        Deal.status: deal_status,
        Deal.contact_id: contact_id,
        Deal.company_id: company_id,
    }
    for column, value in filters.items():
        if value is not None:
            stmt = stmt.where(column == value)
    stmt = stmt.order_by(col(Deal.created_at).desc(), col(Deal.id).desc())
    page = paginate(session, stmt, DealPublic, skip, limit)
    with_deal_names(session, page.data)
    return page


@router.post("", response_model=DealPublic, status_code=status.HTTP_201_CREATED)
def create_deal(session: SessionDep, user: WriterUser, body: DealCreate) -> DealPublic:
    return deal_public(session, actions.create_deal(session, user, body))


@router.get("/{deal_id}", response_model=DealPublic)
def read_deal(session: SessionDep, user: CurrentUser, deal_id: int) -> DealPublic:
    return deal_public(session, get_visible(session, Deal, deal_id, user))


@router.patch("/{deal_id}", response_model=DealPublic)
def update_deal(
    session: SessionDep, user: WriterUser, deal_id: int, body: DealUpdate
) -> DealPublic:
    data = body.model_dump(exclude_unset=True)
    return deal_public(session, actions.update_deal(session, user, deal_id, data))


@router.post("/{deal_id}/won", response_model=DealPublic)
def mark_won(session: SessionDep, user: WriterUser, deal_id: int) -> DealPublic:
    return deal_public(session, actions.mark_won(session, user, deal_id))


@router.post("/{deal_id}/lost", response_model=DealPublic)
def mark_lost(session: SessionDep, user: WriterUser, deal_id: int, body: DealLost) -> DealPublic:
    deal = actions.mark_lost(session, user, deal_id, body.lost_reason_id, body.note)
    return deal_public(session, deal)


@router.post("/{deal_id}/reopen", response_model=DealPublic)
def reopen(session: SessionDep, user: WriterUser, deal_id: int) -> DealPublic:
    return deal_public(session, actions.reopen_deal(session, user, deal_id))


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deal(session: SessionDep, user: WriterUser, deal_id: int) -> Response:
    deal = get_visible(session, Deal, deal_id, user)
    for event in session.exec(select(DealEvent).where(DealEvent.deal_id == deal_id)):
        session.delete(event)
    for proposal in session.exec(select(AgentProposal).where(AgentProposal.deal_id == deal_id)):
        proposal.deal_id = None
        if proposal.status == ProposalStatus.pending:
            proposal.status = ProposalStatus.failed
            proposal.error = "The deal was deleted"
        session.add(proposal)
    for activity in session.exec(select(Activity).where(Activity.deal_id == deal_id)):
        activity.deal_id = None
        session.add(activity)
    session.delete(deal)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{deal_id}/timeline", response_model=list[TimelineItem])
def deal_timeline(session: SessionDep, user: CurrentUser, deal_id: int) -> list[TimelineItem]:
    """Change history and activities for one deal, newest first."""
    get_visible(session, Deal, deal_id, user)
    events = session.exec(select(DealEvent).where(DealEvent.deal_id == deal_id)).all()
    activities = session.exec(select(Activity).where(Activity.deal_id == deal_id)).all()
    names = user_refs(session, [e.actor_id for e in events] + [a.owner_id for a in activities])
    items = [
        TimelineItem(
            kind="event",
            at=e.created_at,
            event=DealEventPublic.model_validate(e),
            actor=names.get(e.actor_id) if e.actor_id else None,
        )
        for e in events
    ] + [
        TimelineItem(
            kind="activity",
            at=a.created_at,
            activity=ActivityPublic.model_validate(a),
            actor=names.get(a.owner_id),
        )
        for a in activities
    ]
    return sorted(items, key=lambda i: i.at, reverse=True)
