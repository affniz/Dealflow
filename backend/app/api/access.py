"""Record-level access rules.

Owners, admins and viewers see every record. Agents see only records they own,
and a record they can't see behaves as if it doesn't exist (404, not 403).
"""

from typing import Any, TypeVar

from fastapi import HTTPException, status
from sqlalchemy import func
from sqlmodel import Session, SQLModel, select

from app.models import Page, Role, User, utcnow

M = TypeVar("M", bound=SQLModel)
P = TypeVar("P", bound=SQLModel)


def sees_all(user: User) -> bool:
    return user.role != Role.agent


def scoped(stmt: Any, model: Any, user: User) -> Any:
    return stmt if sees_all(user) else stmt.where(model.owner_id == user.id)


def _hidden(obj: Any, user: User) -> bool:
    # session.get can hand back a row the session already holds, so check the trash here too
    if getattr(obj, "deleted_at", None) is not None:
        return True
    return not sees_all(user) and obj.owner_id != user.id


def get_visible(session: Session, model: type[M], obj_id: int, user: User) -> M:
    obj = session.get(model, obj_id)
    if obj is None or _hidden(obj, user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


def check_ref(session: Session, model: type[SQLModel], obj_id: int | None, user: User) -> None:
    """Validate a foreign key in a request body: it must exist and be visible to the user."""
    if obj_id is None:
        return
    obj = session.get(model, obj_id)
    if obj is None or _hidden(obj, user):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"{model.__name__} {obj_id} not found"
        )


def resolve_owner(session: Session, user: User, requested: int | None) -> int:
    """Who should own a new or reassigned record."""
    assert user.id is not None
    if requested is None or requested == user.id:
        return user.id
    if user.role == Role.agent:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Agents can only assign records to themselves"
        )
    target = session.get(User, requested)
    if target is None or not target.is_active or target.role == Role.viewer:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"User {requested} can't own records"
        )
    return requested


def apply_update(session: Session, obj: Any, user: User, data: dict[str, Any]) -> list[str]:
    """Apply a PATCH body to a record; returns the names of fields that changed."""
    if "owner_id" in data:
        data["owner_id"] = resolve_owner(session, user, data["owner_id"])
    changed = [k for k, v in data.items() if getattr(obj, k) != v]
    obj.sqlmodel_update(data)
    if hasattr(obj, "updated_at"):
        obj.updated_at = utcnow()
    return changed


def paginate(session: Session, stmt: Any, public: type[P], skip: int, limit: int) -> Page[P]:
    count = session.exec(select(func.count()).select_from(stmt.subquery())).one()
    rows = session.exec(stmt.offset(skip).limit(limit)).all()
    return Page[public](data=[public.model_validate(r) for r in rows], count=count)


def save(session: Session, obj: M) -> M:
    session.add(obj)
    session.commit()
    session.refresh(obj)
    return obj
