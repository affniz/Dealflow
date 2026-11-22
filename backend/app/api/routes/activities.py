from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func
from sqlmodel import Session, col, or_, select

from app.api.access import (
    get_visible,
    paginate,
    scoped,
)
from app.api.deps import CurrentUser, SessionDep, WriterUser
from app.models import (
    Activity,
    ActivityCreate,
    ActivityPublic,
    ActivityType,
    ActivityUpdate,
    Page,
    to_utc,
    utcnow,
)
from app.services import actions
from app.services.names import with_activity_names
from app.services.trash import soft_delete

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=Page[ActivityPublic])
def list_activities(
    session: SessionDep,
    user: CurrentUser,
    deal_id: int | None = None,
    contact_id: int | None = None,
    company_id: int | None = None,
    owner_id: int | None = None,
    type: ActivityType | None = None,
    done: bool | None = None,
    overdue: bool = Query(False, description="Only open activities past their due time"),
    todo: bool | None = Query(
        None,
        description="true: open calls, meetings, tasks and emails (notes are never to-dos); "
        "false: everything else (done items and notes)",
    ),
    due_after: datetime | None = Query(None, description="Due at or after this time"),
    due_before: datetime | None = Query(None, description="Due before this time"),
    has_due: bool | None = Query(None, description="With (true) or without (false) a due time"),
    q: str | None = Query(None, description="Search subject and details"),
    sort: Literal["due", "recent"] = Query(
        "due", description="due: soonest first, undated last; recent: last done or added first"
    ),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Page[ActivityPublic]:
    stmt = scoped(select(Activity), Activity, user)
    filters = {
        Activity.deal_id: deal_id,
        Activity.contact_id: contact_id,
        Activity.company_id: company_id,
        Activity.owner_id: owner_id,
        Activity.type: type,
        Activity.done: done,
    }
    for column, value in filters.items():
        if value is not None:
            stmt = stmt.where(column == value)
    due = col(Activity.due_at)
    if overdue:
        stmt = stmt.where(col(Activity.done).is_(False), due < utcnow())
    if todo is not None:
        is_todo = (col(Activity.done).is_(False)) & (col(Activity.type) != ActivityType.note)
        stmt = stmt.where(is_todo if todo else ~is_todo)
    if due_after is not None:
        stmt = stmt.where(due >= to_utc(due_after))
    if due_before is not None:
        stmt = stmt.where(due < to_utc(due_before))
    if has_due is not None:
        stmt = stmt.where(due.is_not(None) if has_due else due.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(col(Activity.subject).ilike(like), col(Activity.body).ilike(like)))
    if sort == "recent":
        happened = func.coalesce(Activity.done_at, Activity.created_at)
        stmt = stmt.order_by(happened.desc(), col(Activity.id).desc())
    else:
        stmt = stmt.order_by(due.is_(None), due, col(Activity.id))
    page = paginate(session, stmt, ActivityPublic, skip, limit)
    with_activity_names(session, page.data)
    return page


def _public(session: Session, activity: Activity) -> ActivityPublic:
    """With linked names; a link to a deleted record reads as none."""
    return with_activity_names(session, [ActivityPublic.model_validate(activity)])[0]


@router.post("", response_model=ActivityPublic, status_code=status.HTTP_201_CREATED)
def create_activity(session: SessionDep, user: WriterUser, body: ActivityCreate) -> ActivityPublic:
    return _public(session, actions.create_activity(session, user, body))


@router.get("/{activity_id}", response_model=ActivityPublic)
def read_activity(session: SessionDep, user: CurrentUser, activity_id: int) -> ActivityPublic:
    return _public(session, get_visible(session, Activity, activity_id, user))


@router.patch("/{activity_id}", response_model=ActivityPublic)
def update_activity(
    session: SessionDep, user: WriterUser, activity_id: int, body: ActivityUpdate
) -> ActivityPublic:
    data = body.model_dump(exclude_unset=True)
    return _public(session, actions.update_activity(session, user, activity_id, data))


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(session: SessionDep, user: WriterUser, activity_id: int) -> Response:
    soft_delete(session, user, "activity", get_visible(session, Activity, activity_id, user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
