from fastapi import APIRouter, Query, Response, status
from sqlmodel import col, select

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
    ActivityCreate,
    ActivityPublic,
    ActivityType,
    ActivityUpdate,
    Company,
    Contact,
    Deal,
    Page,
    utcnow,
)

router = APIRouter(prefix="/activities", tags=["activities"])


def _check_links(session, user, data: dict) -> None:  # noqa: ANN001
    for key, model in (("deal_id", Deal), ("contact_id", Contact), ("company_id", Company)):
        if key in data:
            check_ref(session, model, data[key], user)


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
    _check_links(session, user, body.model_dump())
    owner_id = resolve_owner(session, user, body.owner_id)
    activity = Activity.model_validate(
        body, update={"owner_id": owner_id, "done_at": utcnow() if body.done else None}
    )
    return save(session, activity)


@router.get("/{activity_id}", response_model=ActivityPublic)
def read_activity(session: SessionDep, user: CurrentUser, activity_id: int) -> Activity:
    return get_visible(session, Activity, activity_id, user)


@router.patch("/{activity_id}", response_model=ActivityPublic)
def update_activity(
    session: SessionDep, user: WriterUser, activity_id: int, body: ActivityUpdate
) -> Activity:
    activity = get_visible(session, Activity, activity_id, user)
    data = body.model_dump(exclude_unset=True)
    _check_links(session, user, data)
    if "done" in data and data["done"] != activity.done:
        data["done_at"] = utcnow() if data["done"] else None
    apply_update(session, activity, user, data)
    return save(session, activity)


@router.delete("/{activity_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_activity(session: SessionDep, user: WriterUser, activity_id: int) -> Response:
    session.delete(get_visible(session, Activity, activity_id, user))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
