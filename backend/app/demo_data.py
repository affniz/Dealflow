"""Load a small, realistic sales team and pipeline for demos and manual testing.

Usage: python -m app.demo_data            load it (run app.initial_data first; refuses to run twice)
       python -m app.demo_data --refresh  the public demo's start-up step: load it if it's missing,
                                          or put it back if it was loaded a day or more ago
       python -m app.demo_data --reset    put it back now
Every demo user's password is "demo-password".

Putting it back wipes the CRM records (deals, contacts, companies, activities, Copilot chats,
agent runs and proposals, pipelines and lost reasons, demo users' access tokens) and loads them
again, dated from now. People keep their ids, so visitors stay signed in, and the AI usage
ledger stays, so the monthly budgets still hold.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlmodel import Session, col, delete, select, update

from app.core.config import settings
from app.core.db import engine
from app.core.security import hash_password
from app.initial_data import add_missing
from app.models import (
    Activity,
    ActivityType,
    AgentConversation,
    AgentProposal,
    AgentRun,
    AIUsage,
    ApiToken,
    AppSetting,
    Company,
    Contact,
    Deal,
    DealEvent,
    DealStatus,
    LostReason,
    Pipeline,
    RecordEvent,
    Role,
    Stage,
    User,
    utcnow,
)
from app.services.rotting import check_rotting

PASSWORD = "demo-password"
RESET_AFTER = timedelta(hours=24)
MARKER = "demo"  # appsetting key: {"loaded_at": ...}
LOCK_KEY = 7_340_118_002  # pg advisory lock id: one load or reset at a time

USERS = [
    ("meera@dealflow.dev", "Meera Iyer", Role.admin),
    ("arjun@dealflow.dev", "Arjun Mehta", Role.agent),
    ("sana@dealflow.dev", "Sana Qureshi", Role.agent),
    ("vikram@dealflow.dev", "Vikram Rao", Role.viewer),
]

COMPANIES = [
    ("Zenith Logistics", "zenithlogistics.in", "Logistics"),
    ("Kaveri Foods", "kaverifoods.in", "FMCG"),
    ("Nimbus Health", "nimbushealth.in", "Healthcare"),
    ("Orbit Fintech", "orbitfin.in", "Fintech"),
    ("Saffron Hotels", "saffronhotels.in", "Hospitality"),
    ("Tarang Media", "tarangmedia.in", "Media"),
    ("Banyan Retail", "banyanretail.in", "Retail"),
]

CONTACTS = [
    ("Priya", "Shah", "Head of Operations", 0),
    ("Rohan", "Gupta", "CTO", 1),
    ("Ananya", "Reddy", "Procurement Lead", 2),
    ("Kabir", "Singh", "VP Finance", 3),
    ("Isha", "Nair", "General Manager", 4),
    ("Dev", "Malhotra", "Marketing Director", 5),
    ("Neha", "Kapoor", "COO", 6),
]

# title, value, stage index, owner (0 Meera, 1 Arjun, 2 Sana), contact index, days in stage
DEALS = [
    ("Fleet tracking rollout", 840000, 3, 1, 0, 3),
    ("Warehouse analytics pilot", 260000, 1, 1, 0, 6),
    ("Annual platform licence", 1200000, 2, 1, 1, 9),
    ("Clinic scheduling suite", 450000, 2, 2, 2, 21),  # stalled
    ("Payments reconciliation", 680000, 1, 2, 3, 4),
    ("Loyalty programme revamp", 320000, 0, 1, 4, 2),
    ("Ad inventory dashboard", 150000, 0, 2, 5, 1),
    ("Multi-city expansion", 950000, 3, 0, 6, 11),
    ("Supplier portal", 210000, 1, 1, 1, 18),  # stalled
]


def account_owners() -> dict[int, int]:
    """Contact index -> owner index, from the deals that use each contact.

    A sales rep only sees contacts and companies they own, so each rep's deals must point at
    their own accounts (otherwise the Copilot can't find or link them for that rep).
    """
    owners: dict[int, int] = {}
    for title, _value, _stage, owner, contact, _days in DEALS:
        if owners.setdefault(contact, owner) != owner:
            raise ValueError(f"{title!r} shares contact {CONTACTS[contact][0]} with another owner")
    return owners


def load(session: Session) -> None:
    if is_loaded(session):
        raise SystemExit("Demo data is already loaded.")
    _populate(session)
    _finish(session)


def reset(session: Session) -> None:
    """Wipe the CRM records and load the demo data again, in one transaction."""
    session.exec(update(AIUsage).values(conversation_id=None, run_id=None))  # keep the ledger
    for model in (
        AgentProposal,
        AgentRun,
        AgentConversation,
        Activity,
        DealEvent,
        RecordEvent,
        Deal,
        Contact,
        Company,
        Stage,
        Pipeline,
        LostReason,
    ):
        session.exec(delete(model))
    not_owners = select(User.id).where(User.role != Role.owner)
    session.exec(delete(ApiToken).where(col(ApiToken.user_id).in_(not_owners)))
    session.expunge_all()  # forget the deleted rows
    add_missing(session)  # the default pipeline and lost reasons
    _populate(session)
    _finish(session)


def refresh(session: Session, now: datetime | None = None) -> str:
    """Load the demo data if it's missing, or put it back once it's RESET_AFTER old.

    Returns what it did: "loaded", "reset" or "fresh"."""
    now = now or utcnow()
    session.connection().execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": LOCK_KEY})
    if not is_loaded(session):
        load(session)
        return "loaded"
    loaded_at = loaded_on(session)
    if loaded_at is not None and now - loaded_at < RESET_AFTER:
        session.commit()  # releases the lock
        return "fresh"
    reset(session)
    return "reset"


def loaded_on(session: Session) -> datetime | None:
    marker = session.get(AppSetting, MARKER)
    if marker is None or "loaded_at" not in marker.value:
        return None
    return datetime.fromisoformat(marker.value["loaded_at"])


def _users(session: Session) -> list[User]:
    """The owner, then the demo team, created or put back as they were."""
    users = [session.exec(select(User).where(User.role == Role.owner)).one()]
    for email, name, role in USERS:
        u = session.exec(select(User).where(User.email == email)).first() or User(email=email)
        u.full_name, u.role, u.is_active = name, role, True
        u.hashed_password = hash_password(PASSWORD)
        session.add(u)
        users.append(u)
    session.flush()
    return users


def _finish(session: Session) -> None:
    marker = session.get(AppSetting, MARKER) or AppSetting(key=MARKER, value={})
    marker.value = {"loaded_at": utcnow().isoformat()}
    marker.updated_at = utcnow()
    session.add(marker)
    session.commit()
    result = check_rotting(session)
    print(f"Demo data loaded ({result.flagged} stalled deals). Password: {PASSWORD}")


def _populate(session: Session) -> None:
    pipeline = session.exec(select(Pipeline).order_by(Pipeline.id)).first()  # type: ignore[arg-type]
    assert pipeline is not None, "Run python -m app.initial_data first"
    stages = sorted(pipeline.stages, key=lambda st: st.position)
    reasons = session.exec(select(LostReason).order_by(col(LostReason.id))).all()
    users = _users(session)
    sellers = users[1:4]  # Meera (admin), Arjun and Sana (agents)

    owner_of_contact = account_owners()
    # each company has one contact here, so it belongs to that contact's owner
    owner_of_company = {CONTACTS[ci][3]: oi for ci, oi in owner_of_contact.items()}
    companies = []
    for i, (name, domain, industry) in enumerate(COMPANIES):
        owner = sellers[owner_of_company.get(i, 0)]
        c = Company(name=name, domain=domain, industry=industry, owner_id=owner.id)
        session.add(c)
        companies.append(c)
    session.flush()

    contacts = []
    for index, (first, last, title, ci) in enumerate(CONTACTS):
        c = Contact(
            first_name=first,
            last_name=last,
            job_title=title,
            email=f"{first.lower()}@{COMPANIES[ci][1]}",
            phone=f"+91 98{ci}00 1{ci}2{ci}3",
            company_id=companies[ci].id,
            owner_id=sellers[owner_of_contact.get(index, 0)].id,
        )
        session.add(c)
        contacts.append(c)
    session.flush()

    now = utcnow()
    for title, value, si, oi, ci, days in DEALS:
        contact = contacts[ci]
        owner_id = sellers[oi].id
        deal = Deal(
            title=title,
            value=Decimal(value),
            currency=settings.DEFAULT_CURRENCY,
            pipeline_id=pipeline.id,  # type: ignore[arg-type]
            stage_id=stages[si].id,  # type: ignore[arg-type]
            owner_id=owner_id,  # type: ignore[arg-type]
            contact_id=contact.id,
            company_id=contact.company_id,
            created_at=now - timedelta(days=days + 5),
            stage_changed_at=now - timedelta(days=days),
        )
        session.add(deal)
        session.flush()
        session.add(
            DealEvent(
                deal_id=deal.id,  # type: ignore[arg-type]
                actor_id=owner_id,
                kind="created",
                data={"stage_id": stages[0].id, "value": str(deal.value)},
                created_at=deal.created_at,
            )
        )
        session.add(
            Activity(
                type=ActivityType.call,
                subject=f"Discovery call with {contact.first_name}",
                body="Walked through current process and pain points.",
                deal_id=deal.id,
                contact_id=contact.id,
                company_id=contact.company_id,
                owner_id=owner_id,  # type: ignore[arg-type]
                done=True,
                done_at=deal.created_at + timedelta(days=1),
                created_at=deal.created_at + timedelta(days=1),
            )
        )

    # some history for the dashboard
    for title, value, status, reason in [
        ("Hotel booking engine", 540000, DealStatus.won, None),
        ("Newsroom CMS", 300000, DealStatus.lost, 0),
        ("Diagnostics integration", 410000, DealStatus.lost, 1),
        ("Freight insurance add-on", 120000, DealStatus.lost, 0),
    ]:
        session.add(
            Deal(
                title=title,
                value=Decimal(value),
                pipeline_id=pipeline.id,  # type: ignore[arg-type]
                stage_id=stages[-1].id,  # type: ignore[arg-type]
                owner_id=sellers[1].id,  # type: ignore[arg-type]
                status=status,
                lost_reason_id=reasons[reason].id if reason is not None else None,
                closed_at=now - timedelta(days=10),
            )
        )


def is_loaded(session: Session) -> bool:
    return session.exec(select(User).where(User.email == USERS[0][0])).first() is not None


if __name__ == "__main__":
    import sys

    with Session(engine) as s:
        if "--refresh" in sys.argv:
            print(f"Demo data: {refresh(s)}")
        elif "--reset" in sys.argv:
            reset(s)
        else:
            load(s)
