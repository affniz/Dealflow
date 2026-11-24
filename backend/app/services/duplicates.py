"""Finding contacts that look like the person someone is about to add or save.

Nothing is blocked: the app shows the likely matches and the person decides (shared addresses
like sales@ or a reception number are legitimate). A contact matches when it has:
- the same email, ignoring case;
- the same phone number, compared on its last 10 digits, so "+91 98765 43210", "098765 43210"
  and "9876543210" are the same number;
- the same full name (ignoring case and spacing) at the same company. A name alone is too
  common to go on.

Only contacts the person can see are matched, and the trash is left out.
"""

import re

from sqlalchemy import func
from sqlmodel import Session, col, or_, select

from app.api.access import scoped
from app.models import Contact, ContactDuplicateCheck, ContactMatch, DuplicateReason, User
from app.services.names import company_refs, contact_name, user_refs

MAX_MATCHES = 5
PHONE_DIGITS = 10  # the part of a number that identifies it, without country or trunk codes
MIN_PHONE_DIGITS = 7  # shorter than this isn't a phone number worth matching on


def phone_key(phone: str | None) -> str | None:
    digits = re.sub(r"\D", "", phone or "")
    return digits[-PHONE_DIGITS:] if len(digits) >= MIN_PHONE_DIGITS else None


def name_key(first: str | None, last: str | None) -> str | None:
    name = " ".join(f"{first or ''} {last or ''}".split()).lower()
    return name or None


def find_duplicates(
    session: Session, user: User, candidate: ContactDuplicateCheck
) -> list[ContactMatch]:
    email = (candidate.email or "").strip().lower() or None
    phone = phone_key(candidate.phone)
    name = name_key(candidate.first_name, candidate.last_name)

    # the same normalising as above, in SQL
    sql_email = func.lower(Contact.email)
    sql_phone = func.right(func.regexp_replace(Contact.phone, r"\D", "", "g"), PHONE_DIGITS)
    sql_name = func.lower(
        func.trim(
            func.regexp_replace(
                func.concat_ws(" ", Contact.first_name, Contact.last_name), r"\s+", " ", "g"
            )
        )
    )
    conditions = []
    if email:
        conditions.append(sql_email == email)
    if phone:
        conditions.append(sql_phone == phone)
    if name and candidate.company_id is not None:
        conditions.append((sql_name == name) & (Contact.company_id == candidate.company_id))
    if not conditions:
        return []

    stmt = scoped(select(Contact), Contact, user).where(or_(*conditions))
    if candidate.exclude_id is not None:
        stmt = stmt.where(Contact.id != candidate.exclude_id)
    rows = session.exec(stmt.order_by(col(Contact.id)).limit(50)).all()

    found: list[tuple[Contact, list[DuplicateReason]]] = []
    for c in rows:
        reasons: list[DuplicateReason] = []
        if email and (c.email or "").lower() == email:
            reasons.append("email")
        if phone and phone_key(c.phone) == phone:
            reasons.append("phone")
        if (
            name
            and candidate.company_id is not None
            and c.company_id == candidate.company_id
            and name_key(c.first_name, c.last_name) == name
        ):
            reasons.append("name")
        if reasons:
            found.append((c, reasons))
    found.sort(key=lambda m: -len(m[1]))  # the closest matches first
    found = found[:MAX_MATCHES]

    companies = company_refs(session, (c.company_id for c, _ in found))
    owners = user_refs(session, (c.owner_id for c, _ in found))
    return [
        ContactMatch(
            id=c.id,  # type: ignore[arg-type]
            name=contact_name(c),
            job_title=c.job_title,
            email=c.email,
            phone=c.phone,
            company=companies.get(c.company_id) if c.company_id else None,
            owner=owners.get(c.owner_id),
            reasons=reasons,
        )
        for c, reasons in found
    ]
