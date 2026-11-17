from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from sqlmodel import Session, col, select

from app.api.access import (
    apply_update,
    check_ref,
    get_visible,
    paginate,
    resolve_owner,
    save,
    scoped,
)
from app.api.deps import CurrentUser, SessionDep, WriterUser
from app.models import (
    Activity,
    ActivityPublic,
    Company,
    Contact,
    Deal,
    DealCreate,
    DealEvent,
    DealEventPublic,
    DealLost,
    DealPublic,
    DealStatus,
    DealUpdate,
    LostReason,
    Page,
    Stage,
    TimelineItem,
    User,
    utcnow,
)
from app.services.names import deal_public, user_refs, with_deal_names

router = APIRouter(prefix="/deals", tags=["deals"])


def _stage_or_422(session: Session, stage_id: int) -> Stage:
    stage = session.get(Stage, stage_id)
    if stage is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Stage {stage_id} not found")
    return stage


def _log(session: Session, deal: Deal, user: User, kind: str, **data: Any) -> None:
    session.add(DealEvent(deal_id=deal.id, actor_id=user.id, kind=kind, data=data))  # type: ignore[arg-type]


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
    stage = _stage_or_422(session, body.stage_id)
    check_ref(session, Contact, body.contact_id, user)
    check_ref(session, Company, body.company_id, user)
    owner_id = resolve_owner(session, user, body.owner_id)
    deal = Deal.model_validate(
        body, update={"owner_id": owner_id, "pipeline_id": stage.pipeline_id}
    )
    session.add(deal)
    session.flush()
    _log(session, deal, user, "created", stage_id=stage.id, value=str(deal.value))
    return deal_public(session, save(session, deal))


@router.get("/{deal_id}", response_model=DealPublic)
def read_deal(session: SessionDep, user: CurrentUser, deal_id: int) -> DealPublic:
    return deal_public(session, get_visible(session, Deal, deal_id, user))


@router.patch("/{deal_id}", response_model=DealPublic)
def update_deal(
    session: SessionDep, user: WriterUser, deal_id: int, body: DealUpdate
) -> DealPublic:
    deal = get_visible(session, Deal, deal_id, user)
    data = body.model_dump(exclude_unset=True)
    if "contact_id" in data:
        check_ref(session, Contact, data["contact_id"], user)
    if "company_id" in data:
        check_ref(session, Company, data["company_id"], user)

    new_stage_id = data.pop("stage_id", deal.stage_id)
    if new_stage_id != deal.stage_id:
        if deal.status != DealStatus.open:
            raise HTTPException(status.HTTP_409_CONFLICT, "Reopen the deal before moving it")
        stage = _stage_or_422(session, new_stage_id)
        _log(
            session, deal, user, "stage_changed", from_stage_id=deal.stage_id, to_stage_id=stage.id
        )
        deal.stage_id = stage.id  # type: ignore[assignment]
        deal.pipeline_id = stage.pipeline_id
        deal.stage_changed_at = utcnow()
        deal.rotting_since = None
        deal.updated_at = utcnow()

    changed = apply_update(session, deal, user, data)
    if changed:
        _log(session, deal, user, "updated", fields=changed)
    return deal_public(session, save(session, deal))


@router.post("/{deal_id}/won", response_model=DealPublic)
def mark_won(session: SessionDep, user: WriterUser, deal_id: int) -> DealPublic:
    deal = get_visible(session, Deal, deal_id, user)
    if deal.status != DealStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Deal is already {deal.status.value}")
    deal.status = DealStatus.won
    deal.closed_at = deal.updated_at = utcnow()
    deal.rotting_since = None
    _log(session, deal, user, "won", value=str(deal.value))
    return deal_public(session, save(session, deal))


@router.post("/{deal_id}/lost", response_model=DealPublic)
def mark_lost(session: SessionDep, user: WriterUser, deal_id: int, body: DealLost) -> DealPublic:
    deal = get_visible(session, Deal, deal_id, user)
    if deal.status != DealStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Deal is already {deal.status.value}")
    reason = session.get(LostReason, body.lost_reason_id)
    if reason is None or not reason.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick a valid lost reason")
    deal.status = DealStatus.lost
    deal.lost_reason_id = reason.id
    deal.lost_note = body.note
    deal.closed_at = deal.updated_at = utcnow()
    deal.rotting_since = None
    _log(session, deal, user, "lost", reason_id=reason.id, reason=reason.label, note=body.note)
    return deal_public(session, save(session, deal))


@router.post("/{deal_id}/reopen", response_model=DealPublic)
def reopen(session: SessionDep, user: WriterUser, deal_id: int) -> DealPublic:
    deal = get_visible(session, Deal, deal_id, user)
    if deal.status == DealStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "Deal is already open")
    _log(session, deal, user, "reopened", previous_status=deal.status.value)
    deal.status = DealStatus.open
    deal.lost_reason_id = deal.lost_note = deal.closed_at = deal.rotting_since = None
    deal.stage_changed_at = deal.updated_at = utcnow()
    return deal_public(session, save(session, deal))


@router.delete("/{deal_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deal(session: SessionDep, user: WriterUser, deal_id: int) -> Response:
    deal = get_visible(session, Deal, deal_id, user)
    for event in session.exec(select(DealEvent).where(DealEvent.deal_id == deal_id)):
        session.delete(event)
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
