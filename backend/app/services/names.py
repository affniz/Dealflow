"""Display names and small counts for linked records, loaded in one query per table."""

from collections.abc import Callable, Iterable
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, SQLModel, col, select

from app.api.access import scoped
from app.models import (
    ActivityPublic,
    Company,
    CompanyPublic,
    Contact,
    ContactPublic,
    Deal,
    DealPublic,
    DealStatus,
    NamedRef,
    User,
)


def user_name(user: User) -> str:
    return user.full_name or user.email


def contact_name(contact: Contact) -> str:
    return " ".join(p for p in (contact.first_name, contact.last_name) if p)


def _refs(
    session: Session, model: Any, ids: Iterable[int | None], name: Callable[[Any], str]
) -> dict[int, NamedRef]:
    wanted = {i for i in ids if i is not None}
    if not wanted:
        return {}
    rows = session.exec(select(model).where(col(model.id).in_(wanted))).all()
    return {r.id: NamedRef(id=r.id, name=name(r)) for r in rows}


def user_refs(session: Session, ids: Iterable[int | None]) -> dict[int, NamedRef]:
    return _refs(session, User, ids, user_name)


def contact_refs(session: Session, ids: Iterable[int | None]) -> dict[int, NamedRef]:
    return _refs(session, Contact, ids, contact_name)


def company_refs(session: Session, ids: Iterable[int | None]) -> dict[int, NamedRef]:
    return _refs(session, Company, ids, lambda c: c.name)


def deal_refs(session: Session, ids: Iterable[int | None]) -> dict[int, NamedRef]:
    return _refs(session, Deal, ids, lambda d: d.title)


def _get(refs: dict[int, NamedRef], key: int | None) -> NamedRef | None:
    return refs.get(key) if key is not None else None


def with_deal_names(session: Session, deals: list[DealPublic]) -> list[DealPublic]:
    """Attach owner, contact and company names to deal responses (mutates and returns)."""
    owners = user_refs(session, (d.owner_id for d in deals))
    contacts = contact_refs(session, (d.contact_id for d in deals))
    companies = company_refs(session, (d.company_id for d in deals))
    for d in deals:
        d.owner = owners.get(d.owner_id)
        d.contact = _get(contacts, d.contact_id)
        d.company = _get(companies, d.company_id)
        # a link to a deleted record reads as no link (and comes back if it's restored)
        d.contact_id = d.contact.id if d.contact else None
        d.company_id = d.company.id if d.company else None
    return deals


def deal_public(session: Session, deal: Deal) -> DealPublic:
    return with_deal_names(session, [DealPublic.model_validate(deal)])[0]


def with_activity_names(session: Session, activities: list[ActivityPublic]) -> list[ActivityPublic]:
    """Attach owner and linked deal, contact and company names (mutates and returns)."""
    owners = user_refs(session, (a.owner_id for a in activities))
    deals = deal_refs(session, (a.deal_id for a in activities))
    contacts = contact_refs(session, (a.contact_id for a in activities))
    companies = company_refs(session, (a.company_id for a in activities))
    for a in activities:
        a.owner = owners.get(a.owner_id)
        a.deal = _get(deals, a.deal_id)
        a.contact = _get(contacts, a.contact_id)
        a.company = _get(companies, a.company_id)
        a.deal_id = a.deal.id if a.deal else None
        a.contact_id = a.contact.id if a.contact else None
        a.company_id = a.company.id if a.company else None
    return activities


def _counts(
    session: Session, user: User, model: type[SQLModel], key: Any, ids: set[int], *where: Any
) -> dict[int, int]:
    """Visible `model` rows per `key` value, for the given ids."""
    if not ids:
        return {}
    stmt = scoped(select(key, func.count()), model, user).where(col(key).in_(ids), *where)
    return dict(session.exec(stmt.group_by(key)).all())  # type: ignore[arg-type]


def with_contact_details(
    session: Session, user: User, contacts: list[ContactPublic]
) -> list[ContactPublic]:
    """Attach owner and company names and the open deals the reader can see."""
    owners = user_refs(session, (c.owner_id for c in contacts))
    companies = company_refs(session, (c.company_id for c in contacts))
    open_deals = _counts(
        session,
        user,
        Deal,
        Deal.contact_id,
        {c.id for c in contacts},
        Deal.status == DealStatus.open,
    )
    for c in contacts:
        c.owner = owners.get(c.owner_id)
        c.company = _get(companies, c.company_id)
        c.company_id = c.company.id if c.company else None
        c.open_deal_count = open_deals.get(c.id, 0)
    return contacts


def contact_public(session: Session, user: User, contact: Contact) -> ContactPublic:
    return with_contact_details(session, user, [ContactPublic.model_validate(contact)])[0]


def with_company_details(
    session: Session, user: User, companies: list[CompanyPublic]
) -> list[CompanyPublic]:
    """Attach owner names, contact counts and open deal totals the reader can see."""
    ids = {c.id for c in companies}
    owners = user_refs(session, (c.owner_id for c in companies))
    people = _counts(session, user, Contact, Contact.company_id, ids)
    deals: dict[int, tuple[int, Decimal]] = {}
    if ids:
        stmt = scoped(
            select(Deal.company_id, func.count(), func.coalesce(func.sum(Deal.value), 0)),
            Deal,
            user,
        ).where(col(Deal.company_id).in_(ids), Deal.status == DealStatus.open)
        for company_id, count, value in session.exec(stmt.group_by(Deal.company_id)).all():
            deals[company_id] = (count, Decimal(value))  # type: ignore[index]
    for c in companies:
        c.owner = owners.get(c.owner_id)
        c.contact_count = people.get(c.id, 0)
        c.open_deal_count, c.open_deal_value = deals.get(c.id, (0, Decimal("0")))
    return companies


def company_public(session: Session, user: User, company: Company) -> CompanyPublic:
    return with_company_details(session, user, [CompanyPublic.model_validate(company)])[0]
