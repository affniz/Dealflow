"""Deleting, restoring and purging records, and contact and company change history.

Deleting a deal, contact, company or activity only marks it (deleted_at): every query then
leaves it out (see SoftDeletable in app.models), but its links, history and activities stay
as they were, so restoring it puts everything back. After TRASH_DAYS the worker purges it
for good; an admin can also purge one sooner from the trash.
"""

from datetime import datetime, timedelta
from typing import Any, Literal

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlmodel import Session, SQLModel, col, delete, select, update

from app.api.access import sees_all
from app.core.config import settings
from app.models import (
    Activity,
    AgentProposal,
    AgentRun,
    Company,
    Contact,
    Deal,
    DealEvent,
    HistoryItem,
    ProposalStatus,
    RecordEvent,
    Role,
    TrashItem,
    User,
    utcnow,
)
from app.services.names import contact_name, user_refs

RecordType = Literal["deal", "contact", "company", "activity"]
MODELS: dict[str, type[Any]] = {
    "deal": Deal,
    "contact": Contact,
    "company": Company,
    "activity": Activity,
}
INCLUDE_DELETED = {"include_deleted": True}
# fields not worth a line in the history
QUIET_FIELDS = {"updated_at", "created_at", "id"}


def _name(record_type: str, row: Any) -> str:
    if record_type == "deal":
        return row.title
    if record_type == "contact":
        return contact_name(row)
    if record_type == "company":
        return row.name
    return row.subject


def _retention() -> timedelta:
    return timedelta(days=settings.TRASH_DAYS)


# ------------------------------------------------------------------ history


def snapshot(obj: SQLModel) -> dict[str, Any]:
    """A record's fields as JSON-ready values, to compare before and after a change."""
    return jsonable_encoder(obj.model_dump(exclude=QUIET_FIELDS))


def changes(before: dict[str, Any], after: dict[str, Any]) -> dict[str, list[Any]]:
    """{field: [old, new]} for the fields that differ."""
    return {k: [before.get(k), v] for k, v in after.items() if before.get(k) != v}


def log_record(
    session: Session,
    record_type: Literal["contact", "company"],
    record_id: int,
    user: User | None,
    kind: str,
    **data: Any,
) -> None:
    session.add(
        RecordEvent(
            record_type=record_type,
            record_id=record_id,
            actor_id=user.id if user else None,
            kind=kind,
            data=jsonable_encoder(data),
        )
    )


def history(
    session: Session, record_type: Literal["contact", "company"], record_id: int
) -> list[HistoryItem]:
    """The record's changes, newest first."""
    events = session.exec(
        select(RecordEvent)
        .where(RecordEvent.record_type == record_type, RecordEvent.record_id == record_id)
        .order_by(col(RecordEvent.created_at).desc(), col(RecordEvent.id).desc())
    ).all()
    names = user_refs(session, (e.actor_id for e in events))
    return [
        HistoryItem(
            id=e.id,  # type: ignore[arg-type]
            kind=e.kind,
            data=e.data,
            created_at=e.created_at,
            actor=names.get(e.actor_id) if e.actor_id else None,
        )
        for e in events
    ]


# ------------------------------------------------------------------ deleting and restoring


def soft_delete(session: Session, user: User, record_type: RecordType, row: Any) -> None:
    """Move a record the user can already see to the trash, and commit."""
    row.deleted_at = utcnow()
    row.deleted_by_id = user.id
    session.add(row)
    if record_type == "deal":
        session.add(DealEvent(deal_id=row.id, actor_id=user.id, kind="deleted", data={}))
        # suggestions for it can't be approved while it's gone
        session.exec(
            update(AgentProposal)
            .where(
                col(AgentProposal.deal_id) == row.id,
                AgentProposal.status == ProposalStatus.pending,
            )
            .values(status=ProposalStatus.failed, error="The deal was deleted")
        )
    elif record_type in ("contact", "company"):
        log_record(session, record_type, row.id, user, "deleted")
    session.commit()


def _deleted(session: Session, user: User, record_type: str, record_id: int) -> Any:
    """A record in the trash that this person can see, or 404."""
    model = MODELS.get(record_type)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    row = session.get(model, record_id, execution_options=INCLUDE_DELETED)
    if row is None or row.deleted_at is None or (not sees_all(user) and row.owner_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No deleted {record_type} {record_id}")
    return row


def restore(session: Session, user: User, record_type: str, record_id: int) -> None:
    if user.role == Role.viewer:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed for your role")
    row = _deleted(session, user, record_type, record_id)
    row.deleted_at = None
    row.deleted_by_id = None
    session.add(row)
    if record_type == "deal":
        session.add(DealEvent(deal_id=row.id, actor_id=user.id, kind="restored", data={}))
    elif record_type in ("contact", "company"):
        log_record(session, record_type, row.id, user, "restored")  # type: ignore[arg-type]
    session.commit()


def purge(session: Session, record_type: str, record_id: int) -> None:
    """Delete a record for good: its history goes, and other records lose the link to it.
    Doesn't commit. (Bulk UPDATE/DELETE statements, so rows in the trash are included.)"""
    model = MODELS[record_type]
    if record_type == "deal":
        session.exec(delete(DealEvent).where(col(DealEvent.deal_id) == record_id))
        for linked in (AgentRun, AgentProposal, Activity):  # keep them, minus the link
            session.exec(
                update(linked).where(col(linked.deal_id) == record_id).values(deal_id=None)
            )
    elif record_type == "contact":
        for linked in (Deal, Activity):
            session.exec(
                update(linked).where(col(linked.contact_id) == record_id).values(contact_id=None)
            )
    elif record_type == "company":
        for linked in (Contact, Deal, Activity):
            session.exec(
                update(linked).where(col(linked.company_id) == record_id).values(company_id=None)
            )
    if record_type in ("contact", "company"):
        session.exec(
            delete(RecordEvent).where(
                RecordEvent.record_type == record_type, col(RecordEvent.record_id) == record_id
            )
        )
    session.exec(delete(model).where(col(model.id) == record_id))


def purge_one(session: Session, user: User, record_type: str, record_id: int) -> None:
    """An admin emptying one item from the trash before its time."""
    if user.role not in (Role.owner, Role.admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only admins can delete for good")
    _deleted(session, user, record_type, record_id)
    session.expunge_all()  # the bulk statements below change rows this session may hold
    purge(session, record_type, record_id)
    session.commit()


def purge_expired(session: Session, now: datetime | None = None) -> dict[str, int]:
    """The worker's daily sweep: purge everything deleted more than TRASH_DAYS ago."""
    cutoff = (now or utcnow()) - _retention()
    purged: dict[str, int] = {}
    # activities first, then deals, contacts and companies, so links are cleared in order
    for record_type in ("activity", "deal", "contact", "company"):
        model = MODELS[record_type]
        ids = session.exec(
            select(model.id)
            .where(col(model.deleted_at) <= cutoff)
            .execution_options(**INCLUDE_DELETED)
        ).all()
        for record_id in ids:
            purge(session, record_type, record_id)
        purged[record_type] = len(ids)
    session.commit()
    return purged


# ------------------------------------------------------------------ the trash


def trash(session: Session, user: User) -> list[TrashItem]:
    """Deleted records this person can see, most recently deleted first. Agents see their
    own; everyone else sees the team's."""
    rows: list[tuple[str, Any]] = []
    for record_type, model in MODELS.items():
        stmt = (
            select(model)
            .where(col(model.deleted_at).is_not(None))
            .execution_options(**INCLUDE_DELETED)
        )
        if not sees_all(user):
            stmt = stmt.where(model.owner_id == user.id)
        rows += [(record_type, row) for row in session.exec(stmt).all()]
    names = user_refs(session, (row.deleted_by_id for _, row in rows))
    items = [
        TrashItem(
            type=record_type,  # type: ignore[arg-type]
            id=row.id,
            name=_name(record_type, row),
            deleted_at=row.deleted_at,
            deleted_by=names.get(row.deleted_by_id) if row.deleted_by_id else None,
            purge_after=row.deleted_at + _retention(),
        )
        for record_type, row in rows
    ]
    return sorted(items, key=lambda i: i.deleted_at, reverse=True)
