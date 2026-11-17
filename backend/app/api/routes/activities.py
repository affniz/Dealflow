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
    ActivityCreate,
    ActivityPublic,
    ActivityType,
    ActivityUpdate,
    Page,
    utcnow,
)
from app.services import actions

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=Page[ActivityPublic])
def list_activities(
    session: SessionDep,
    user: CurrentUser,
    deal_id: int | None = None,
    contact_id: int | None = None,
    company_id: int | None = None,
    type: ActivityType | None = None,
    done: bool | None = None,
    overdue: bool = Query(False, description="Only open activities past their due time"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Page[ActivityPublic]:
    stmt = scoped(select(Activity), Activity, user)
    filters = {
        Activity.deal_id: deal_id,
        Activity.contact_id: contact_id,
        Activity.company_id: company_id,
        Activity.type: type,
        Activity.done: done,
    }
    for column, value in filters.items():
        if value is not None:
            stmt = stmt.where(column == value)
    if overdue:
        stmt = stmt.where(col(Activity.done).is_(False), col(Activity.due_at) < utcnow())
    stmt = stmt.order_by(col(Activity.due_at).is_(None), col(Activity.due_at), col(Activity.id))
    return paginate(session, stmt, ActivityPublic, skip, limit)


@router.post("", response_model=ActivityPublic, status_code=status.HTTP_201_CREATED)
def create_activity(session: SessionDep, user: WriterUser, body: ActivityCreate) -> Activity:
    return actions.create_activity(session, user, body)


@router.get("/{activity_id}", response_model=ActivityPublic)
def read_activity(session: SessionDep, user: CurrentUser, activity_id: int) -> Activity:
    return get_visible(session, Activity, activity_id, user)


@router.patch("/{activity_id}", response_model=ActivityPublic)
def update_activity(
    session: SessionDep, user: WriterUser, activity_id: int, body: ActivityUpdate
) -> Activity:
    data = body.model_dump(exclude_unset=True)
    return actions.update_activity(session, user, activity_id, data)


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(session: SessionDep, user: WriterUser, activity_id: int) -> Response:
    session.delete(get_visible(session, Activity, activity_id, user))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
