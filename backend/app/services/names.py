"""Display names for linked records, loaded in one query per table."""

from collections.abc import Iterable

from sqlmodel import Session, col, select

from app.models import Company, Contact, Deal, DealPublic, NamedRef, User


def user_name(user: User) -> str:
    return user.full_name or user.email


def contact_name(contact: Contact) -> str:
    return " ".join(p for p in (contact.first_name, contact.last_name) if p)


def user_refs(session: Session, ids: Iterable[int | None]) -> dict[int, NamedRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    users = session.exec(select(User).where(col(User.id).in_(wanted))).all()
    return {u.id: NamedRef(id=u.id, name=user_name(u)) for u in users}  # type: ignore[misc]


def with_deal_names(session: Session, deals: list[DealPublic]) -> list[DealPublic]:
    """Attach owner, contact and company names to deal responses (mutates and returns)."""
    owners = user_refs(session, (d.owner_id for d in deals))
    contact_ids = {d.contact_id for d in deals if d.contact_id is not None}
    company_ids = {d.company_id for d in deals if d.company_id is not None}
    contacts = (
        {
            c.id: NamedRef(id=c.id, name=contact_name(c))  # type: ignore[arg-type]
            for c in session.exec(select(Contact).where(col(Contact.id).in_(contact_ids))).all()
        }
        if contact_ids
        else {}
    )
    companies = (
        {
            c.id: NamedRef(id=c.id, name=c.name)  # type: ignore[arg-type]
            for c in session.exec(select(Company).where(col(Company.id).in_(company_ids))).all()
        }
        if company_ids
        else {}
    )
    for d in deals:
        d.owner = owners.get(d.owner_id)
        d.contact = contacts.get(d.contact_id) if d.contact_id else None
        d.company = companies.get(d.company_id) if d.company_id else None
    return deals


def deal_public(session: Session, deal: Deal) -> DealPublic:
    return with_deal_names(session, [DealPublic.model_validate(deal)])[0]
