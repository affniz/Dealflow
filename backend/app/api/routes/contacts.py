from fastapi import APIRouter, Query, Response, status
from sqlmodel import col, or_, select

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
    Company,
    Contact,
    ContactCreate,
    ContactPublic,
    ContactUpdate,
    Deal,
    Page,
)

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=Page[ContactPublic])
def list_contacts(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(None, description="Search name, email or phone"),
    company_id: int | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Page[ContactPublic]:
    stmt = scoped(select(Contact), Contact, user)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(
                col(Contact.first_name).ilike(like),
                col(Contact.last_name).ilike(like),
                col(Contact.email).ilike(like),
                col(Contact.phone).ilike(like),
            )
        )
    if company_id is not None:
        stmt = stmt.where(Contact.company_id == company_id)
    stmt = stmt.order_by(col(Contact.first_name), col(Contact.last_name))
    return paginate(session, stmt, ContactPublic, skip, limit)


@router.post("", response_model=ContactPublic, status_code=status.HTTP_201_CREATED)
def create_contact(session: SessionDep, user: WriterUser, body: ContactCreate) -> Contact:
    check_ref(session, Company, body.company_id, user)
    owner_id = resolve_owner(session, user, body.owner_id)
    return save(session, Contact.model_validate(body, update={"owner_id": owner_id}))


@router.get("/{contact_id}", response_model=ContactPublic)
def read_contact(session: SessionDep, user: CurrentUser, contact_id: int) -> Contact:
    return get_visible(session, Contact, contact_id, user)


@router.patch("/{contact_id}", response_model=ContactPublic)
def update_contact(
    session: SessionDep, user: WriterUser, contact_id: int, body: ContactUpdate
) -> Contact:
    contact = get_visible(session, Contact, contact_id, user)
    data = body.model_dump(exclude_unset=True)
    if "company_id" in data:
        check_ref(session, Company, data["company_id"], user)
    apply_update(session, contact, user, data)
    return save(session, contact)


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(session: SessionDep, user: WriterUser, contact_id: int) -> Response:
    contact = get_visible(session, Contact, contact_id, user)
    for model in (Deal, Activity):
        for row in session.exec(select(model).where(model.contact_id == contact_id)):
            row.contact_id = None
            session.add(row)
    session.delete(contact)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
