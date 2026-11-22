from typing import Literal

from fastapi import APIRouter, Query, Response, status
from sqlalchemy import func
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
    Company,
    Contact,
    ContactCreate,
    ContactPublic,
    ContactUpdate,
    HistoryItem,
    Page,
)
from app.services.names import contact_public, with_contact_details
from app.services.trash import changes, history, log_record, snapshot, soft_delete

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=Page[ContactPublic])
def list_contacts(
    session: SessionDep,
    user: CurrentUser,
    q: str | None = Query(None, description="Search name, email, phone or company name"),
    company_id: int | None = None,
    owner_id: int | None = None,
    sort: Literal["name", "recent"] = Query("name", description="Name, or recently updated"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
) -> Page[ContactPublic]:
    stmt = scoped(select(Contact), Contact, user)
    if q:
        like = f"%{q.strip()}%"
        full_name = func.concat_ws(" ", Contact.first_name, Contact.last_name)
        stmt = stmt.outerjoin(Company, col(Company.id) == col(Contact.company_id)).where(
            or_(
                full_name.ilike(like),
                col(Contact.email).ilike(like),
                col(Contact.phone).ilike(like),
                col(Company.name).ilike(like),
            )
        )
    if company_id is not None:
        stmt = stmt.where(Contact.company_id == company_id)
    if owner_id is not None:
        stmt = stmt.where(Contact.owner_id == owner_id)
    if sort == "recent":
        stmt = stmt.order_by(col(Contact.updated_at).desc(), col(Contact.id).desc())
    else:
        stmt = stmt.order_by(
            func.lower(Contact.first_name), func.lower(Contact.last_name), col(Contact.id)
        )
    page = paginate(session, stmt, ContactPublic, skip, limit)
    with_contact_details(session, user, page.data)
    return page


@router.post("", response_model=ContactPublic, status_code=status.HTTP_201_CREATED)
def create_contact(session: SessionDep, user: WriterUser, body: ContactCreate) -> ContactPublic:
    check_ref(session, Company, body.company_id, user)
    owner_id = resolve_owner(session, user, body.owner_id)
    contact = Contact.model_validate(body, update={"owner_id": owner_id})
    session.add(contact)
    session.flush()
    log_record(session, "contact", contact.id, user, "created")  # type: ignore[arg-type]
    return contact_public(session, user, save(session, contact))


@router.get("/{contact_id}", response_model=ContactPublic)
def read_contact(session: SessionDep, user: CurrentUser, contact_id: int) -> ContactPublic:
    return contact_public(session, user, get_visible(session, Contact, contact_id, user))


@router.patch("/{contact_id}", response_model=ContactPublic)
def update_contact(
    session: SessionDep, user: WriterUser, contact_id: int, body: ContactUpdate
) -> ContactPublic:
    contact = get_visible(session, Contact, contact_id, user)
    data = body.model_dump(exclude_unset=True)
    if "company_id" in data and data["company_id"] != contact.company_id:
        check_ref(session, Company, data["company_id"], user)
    before = snapshot(contact)
    apply_update(session, contact, user, data)
    if diff := changes(before, snapshot(contact)):
        log_record(session, "contact", contact_id, user, "updated", changes=diff)
    return contact_public(session, user, save(session, contact))


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(session: SessionDep, user: WriterUser, contact_id: int) -> Response:
    """Moves the contact to the trash; their deals and activities keep the link, which comes
    back if they're restored."""
    soft_delete(session, user, "contact", get_visible(session, Contact, contact_id, user))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{contact_id}/history", response_model=list[HistoryItem])
def contact_history(session: SessionDep, user: CurrentUser, contact_id: int) -> list[HistoryItem]:
    """Who created, changed, deleted or restored this contact, and what changed; newest first."""
    get_visible(session, Contact, contact_id, user)
    return history(session, "contact", contact_id)
