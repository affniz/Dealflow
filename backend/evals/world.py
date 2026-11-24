"""Building the CRM situation a scenario needs, with a history spread over past weeks."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from sqlmodel import Session, select

from app.models import (
    Activity,
    ActivityType,
    Company,
    Contact,
    Deal,
    DealEvent,
    LostReason,
    Pipeline,
    Role,
    Stage,
    User,
    utcnow,
)
from app.services.rotting import AUTO_REMINDER, check_rotting


@dataclass
class World:
    """What a scenario built, by the keys it gave each record."""

    session: Session
    now: datetime
    users: dict[str, User] = field(default_factory=dict)
    contacts: dict[str, Contact] = field(default_factory=dict)
    deals: dict[str, Deal] = field(default_factory=dict)
    activities: dict[str, Activity] = field(default_factory=dict)
    stages: dict[str, Stage] = field(default_factory=dict)
    lost_reasons: dict[str, LostReason] = field(default_factory=dict)

    def reminder(self, deal: str) -> Activity | None:
        """The automatic stalled-deal reminder on a deal, if the stalled check added one."""
        return self.session.exec(
            select(Activity).where(
                Activity.deal_id == self.deals[deal].id, Activity.via == AUTO_REMINDER
            )
        ).first()


class Builder:
    """Adds records to the default "Sales" pipeline that init_db creates. Times are given in
    days before now, so the agent sees a believable history whenever the eval runs."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.world = World(session=session, now=utcnow())
        self.pipeline = session.exec(select(Pipeline)).one()
        self.world.stages = {s.name: s for s in session.exec(select(Stage)).all()}
        self.world.lost_reasons = {r.label: r for r in session.exec(select(LostReason)).all()}
        self.world.users["owner"] = session.exec(select(User).where(User.role == Role.owner)).one()
        self.companies: dict[str, Company] = {}

    def ago(self, days: float) -> datetime:
        return self.world.now - timedelta(days=days)

    def _save(self, *rows: object) -> None:
        self.session.add_all(rows)
        self.session.flush()

    def user(self, key: str, name: str, role: Role) -> User:
        first = name.split()[0].lower()
        # "!" matches no password: nobody signs in as them; the evals act as them directly
        user = User(
            email=f"{first}@evals.dealflow.dev", full_name=name, role=role, hashed_password="!"
        )
        self._save(user)
        self.world.users[key] = user
        return user

    def company(self, name: str, industry: str | None = None) -> Company:
        company = Company(name=name, industry=industry, owner_id=self.world.users["owner"].id)
        self._save(company)
        self.companies[name] = company
        return company

    def contact(
        self,
        key: str,
        name: str,
        company: str,
        owner: str,
        job_title: str | None = None,
    ) -> Contact:
        first, _, last = name.partition(" ")
        contact = Contact(
            first_name=first,
            last_name=last or None,
            email=f"{first.lower()}@{company.split()[0].lower()}.example",
            job_title=job_title,
            company_id=self.companies[company].id,
            owner_id=self.world.users[owner].id,
        )
        self._save(contact)
        self.world.contacts[key] = contact
        return contact

    def deal(
        self,
        key: str,
        title: str,
        value: int,
        stage: str,
        owner: str,
        *,
        days_in_stage: float,
        created_days_ago: float,
        contact: str | None = None,
        company: str | None = None,
    ) -> Deal:
        user = self.world.users[owner]
        contact_row = self.world.contacts[contact] if contact else None
        company_id = (
            self.companies[company].id
            if company
            else contact_row.company_id
            if contact_row
            else None
        )
        deal = Deal(
            title=title,
            value=Decimal(value),
            pipeline_id=self.pipeline.id,  # type: ignore[arg-type]
            stage_id=self.world.stages[stage].id,  # type: ignore[arg-type]
            owner_id=user.id,  # type: ignore[arg-type]
            contact_id=contact_row.id if contact_row else None,
            company_id=company_id,
            stage_changed_at=self.ago(days_in_stage),
            created_at=self.ago(created_days_ago),
            updated_at=self.ago(min(days_in_stage, created_days_ago)),
        )
        self._save(deal)
        first_stage = "Lead" if stage != "Lead" else stage
        self._save(
            DealEvent(
                deal_id=deal.id,  # type: ignore[arg-type]
                actor_id=user.id,
                kind="created",
                data={"stage_id": self.world.stages[first_stage].id, "value": str(value)},
                created_at=self.ago(created_days_ago),
            )
        )
        self.world.deals[key] = deal
        return deal

    def moved(self, deal: str, from_stage: str, to_stage: str, days_ago: float) -> None:
        row = self.world.deals[deal]
        self._save(
            DealEvent(
                deal_id=row.id,  # type: ignore[arg-type]
                actor_id=row.owner_id,
                kind="stage_changed",
                data={
                    "from_stage_id": self.world.stages[from_stage].id,
                    "to_stage_id": self.world.stages[to_stage].id,
                },
                created_at=self.ago(days_ago),
            )
        )

    def activity(
        self,
        deal: str,
        type: ActivityType,
        subject: str,
        *,
        days_ago: float,
        body: str | None = None,
        due_in_days: float | None = None,
        key: str | None = None,
    ) -> Activity:
        """Done `days_ago`, or (with due_in_days) an open one added then and due later."""
        row = self.world.deals[deal]
        done = due_in_days is None
        activity = Activity(
            type=type,
            subject=subject,
            body=body,
            deal_id=row.id,
            contact_id=row.contact_id,
            company_id=row.company_id,
            owner_id=row.owner_id,
            done=done,
            done_at=self.ago(days_ago) if done else None,
            due_at=self.ago(days_ago) if done else self.world.now + timedelta(days=due_in_days),
            created_at=self.ago(days_ago),
        )
        self._save(activity)
        if key:
            self.world.activities[key] = activity
        return activity

    def finish(self) -> World:
        """Flag the stalled deals (adding Dealflow's automatic reminders), as the worker would."""
        check_rotting(self.session, now=self.world.now)
        self.session.commit()
        return self.world
