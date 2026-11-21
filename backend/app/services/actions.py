"""Every change to deals and activities, written once.

The REST routes, the Copilot (when a person approves its proposal) and the pipeline agent all
call these functions, so the same access rules, validation and timeline entries apply whoever
acts. `via` records an AI origin on the timeline ("copilot", "pipeline_agent").

Each function checks that `user` may make the change, applies it and commits.
"""

from typing import Any

from fastapi import HTTPException, status
from sqlmodel import Session

from app.api.access import apply_update, check_ref, get_visible, resolve_owner
from app.core.config import settings
from app.models import (
    Activity,
    ActivityCreate,
    Company,
    Contact,
    Deal,
    DealCreate,
    DealEvent,
    DealStatus,
    LostReason,
    Role,
    Stage,
    User,
    utcnow,
)


def require_writer(user: User) -> None:
    if user.role == Role.viewer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Viewers can't make changes")


def _stage(session: Session, stage_id: int) -> Stage:
    stage = session.get(Stage, stage_id)
    if stage is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Stage {stage_id} not found")
    return stage


def _log(session: Session, deal: Deal, user: User, kind: str, via: str | None, **data: Any) -> None:
    if via:
        data["via"] = via
    session.add(DealEvent(deal_id=deal.id, actor_id=user.id, kind=kind, data=data))  # type: ignore[arg-type]


def _commit(session: Session, obj: Any) -> Any:
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj


# ---------------------------------------------------------------- deals


def _team_currency(currency: str) -> str:
    """Deals must be in the team's currency: the board, dashboard, forecasts and the agents add
    deal values together, and Dealflow doesn't convert between currencies."""
    code = currency.upper()
    if code != settings.DEFAULT_CURRENCY:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Deals are in {settings.DEFAULT_CURRENCY} here; other currencies aren't supported yet",
        )
    return code


def create_deal(session: Session, user: User, body: DealCreate, via: str | None = None) -> Deal:
    require_writer(user)
    stage = _stage(session, body.stage_id)
    check_ref(session, Contact, body.contact_id, user)
    check_ref(session, Company, body.company_id, user)
    owner_id = resolve_owner(session, user, body.owner_id)
    currency = body.currency if "currency" in body.model_fields_set else settings.DEFAULT_CURRENCY
    deal = Deal.model_validate(
        body,
        update={
            "owner_id": owner_id,
            "pipeline_id": stage.pipeline_id,
            "currency": _team_currency(currency),
        },
    )
    session.add(deal)
    session.flush()
    _log(session, deal, user, "created", via, stage_id=stage.id, value=str(deal.value))
    return _commit(session, deal)


def update_deal(
    session: Session, user: User, deal_id: int, data: dict[str, Any], via: str | None = None
) -> Deal:
    """Partial update. A `stage_id` moves the deal (open deals only) and resets its stage clock."""
    require_writer(user)
    deal = get_visible(session, Deal, deal_id, user)
    data = dict(data)
    if data.get("currency") is not None:
        data["currency"] = _team_currency(data["currency"])
    if "contact_id" in data:
        check_ref(session, Contact, data["contact_id"], user)
    if "company_id" in data:
        check_ref(session, Company, data["company_id"], user)

    new_stage_id = data.pop("stage_id", deal.stage_id)
    if new_stage_id != deal.stage_id:
        if deal.status != DealStatus.open:
            raise HTTPException(status.HTTP_409_CONFLICT, "Reopen the deal before moving it")
        stage = _stage(session, new_stage_id)
        _log(
            session,
            deal,
            user,
            "stage_changed",
            via,
            from_stage_id=deal.stage_id,
            to_stage_id=stage.id,
        )
        deal.stage_id = stage.id  # type: ignore[assignment]
        deal.pipeline_id = stage.pipeline_id
        deal.stage_changed_at = deal.updated_at = utcnow()
        deal.rotting_since = None

    changed = apply_update(session, deal, user, data)
    if changed:
        _log(session, deal, user, "updated", via, fields=changed)
    return _commit(session, deal)


def mark_won(session: Session, user: User, deal_id: int, via: str | None = None) -> Deal:
    require_writer(user)
    deal = get_visible(session, Deal, deal_id, user)
    if deal.status != DealStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Deal is already {deal.status.value}")
    deal.status = DealStatus.won
    deal.closed_at = deal.updated_at = utcnow()
    deal.rotting_since = None
    _log(session, deal, user, "won", via, value=str(deal.value))
    return _commit(session, deal)


def mark_lost(
    session: Session,
    user: User,
    deal_id: int,
    lost_reason_id: int,
    note: str | None = None,
    via: str | None = None,
) -> Deal:
    require_writer(user)
    deal = get_visible(session, Deal, deal_id, user)
    if deal.status != DealStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Deal is already {deal.status.value}")
    reason = session.get(LostReason, lost_reason_id)
    if reason is None or not reason.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Pick a valid lost reason")
    deal.status = DealStatus.lost
    deal.lost_reason_id = reason.id
    deal.lost_note = note
    deal.closed_at = deal.updated_at = utcnow()
    deal.rotting_since = None
    _log(session, deal, user, "lost", via, reason_id=reason.id, reason=reason.label, note=note)
    return _commit(session, deal)


def reopen_deal(session: Session, user: User, deal_id: int, via: str | None = None) -> Deal:
    require_writer(user)
    deal = get_visible(session, Deal, deal_id, user)
    if deal.status == DealStatus.open:
        raise HTTPException(status.HTTP_409_CONFLICT, "Deal is already open")
    _log(session, deal, user, "reopened", via, previous_status=deal.status.value)
    deal.status = DealStatus.open
    deal.lost_reason_id = deal.lost_note = deal.closed_at = deal.rotting_since = None
    deal.stage_changed_at = deal.updated_at = utcnow()
    return _commit(session, deal)


# ---------------------------------------------------------------- activities

_LINKS = (("deal_id", Deal), ("contact_id", Contact), ("company_id", Company))


def _check_links(session: Session, user: User, data: dict[str, Any]) -> None:
    for key, model in _LINKS:
        if key in data:
            check_ref(session, model, data[key], user)


def create_activity(
    session: Session, user: User, body: ActivityCreate, via: str | None = None
) -> Activity:
    require_writer(user)
    _check_links(session, user, body.model_dump())
    owner_id = resolve_owner(session, user, body.owner_id)
    activity = Activity.model_validate(
        body, update={"owner_id": owner_id, "done_at": utcnow() if body.done else None}
    )
    activity.via = via
    return _commit(session, activity)


def update_activity(
    session: Session, user: User, activity_id: int, data: dict[str, Any]
) -> Activity:
    require_writer(user)
    activity = get_visible(session, Activity, activity_id, user)
    data = dict(data)
    _check_links(session, user, data)
    if "done" in data and data["done"] != activity.done:
        data["done_at"] = utcnow() if data["done"] else None
    apply_update(session, activity, user, data)
    return _commit(session, activity)
