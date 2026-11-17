"""Load a small, realistic sales team and pipeline for demos and manual testing.

Usage: python -m app.demo_data   (run app.initial_data first; refuses to run twice)
Every demo user's password is "demo-password".
"""

from datetime import timedelta
from decimal import Decimal

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.security import hash_password
from app.models import (
    Activity,
    ActivityType,
    Company,
    Contact,
    Deal,
    DealEvent,
    DealStatus,
    LostReason,
    Pipeline,
    Role,
    User,
    utcnow,
)
from app.services.rotting import check_rotting

PASSWORD = "demo-password"

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
]

CONTACTS = [
    ("Priya", "Shah", "Head of Operations", 0),
    ("Rohan", "Gupta", "CTO", 1),
    ("Ananya", "Reddy", "Procurement Lead", 2),
    ("Kabir", "Singh", "VP Finance", 3),
    ("Isha", "Nair", "General Manager", 4),
    ("Dev", "Malhotra", "Marketing Director", 5),
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
    ("Multi-city expansion", 950000, 3, 0, 4, 11),
    ("Supplier portal", 210000, 1, 1, 1, 18),  # stalled
]


def load(session: Session) -> None:
    if session.exec(select(User).where(User.email == USERS[0][0])).first():
        raise SystemExit("Demo data is already loaded.")
    owner = session.exec(select(User).where(User.role == Role.owner)).one()
    pipeline = session.exec(select(Pipeline).order_by(Pipeline.id)).first()  # type: ignore[arg-type]
    assert pipeline is not None, "Run python -m app.initial_data first"
    stages = pipeline.stages
    reasons = session.exec(select(LostReason)).all()

    users = [owner]
    for email, name, role in USERS:
        u = User(email=email, full_name=name, role=role, hashed_password=hash_password(PASSWORD))
        session.add(u)
        users.append(u)
    session.flush()
    sellers = users[1:4]  # Meera (admin), Arjun and Sana (agents)

    companies = []
    for i, (name, domain, industry) in enumerate(COMPANIES):
        c = Company(name=name, domain=domain, industry=industry, owner_id=sellers[i % 3].id)
        session.add(c)
        companies.append(c)
    session.flush()

    contacts = []
    for first, last, title, ci in CONTACTS:
        c = Contact(
            first_name=first,
            last_name=last,
            job_title=title,
            email=f"{first.lower()}@{COMPANIES[ci][1]}",
            phone=f"+91 98{ci}00 1{ci}2{ci}3",
            company_id=companies[ci].id,
            owner_id=companies[ci].owner_id,
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
    session.commit()
    result = check_rotting(session)
    print(f"Demo data loaded ({result.flagged} stalled deals). Password: {PASSWORD}")


if __name__ == "__main__":
    with Session(engine) as s:
        load(s)
