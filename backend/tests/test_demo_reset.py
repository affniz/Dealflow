"""The public demo goes back to its sample data every day, and the scheduled jobs still run on
a host that sleeps through the hour they're due."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlmodel import Session, col, func, select

from app import demo_data
from app.models import (
    AgentConversation,
    AIUsage,
    ApiToken,
    Deal,
    Pipeline,
    Stage,
    User,
)
from app.services.daily import claim_daily_run


def count(session: Session, model: type) -> int:
    return session.exec(select(func.count()).select_from(model)).one()


def test_reset_puts_the_demo_back_and_keeps_people_and_spending(session):
    demo_data.load(session)
    deals = count(session, Deal)
    arjun = session.exec(select(User).where(User.email == "arjun@dealflow.dev")).one()
    arjun_id = arjun.id

    # a visitor makes a mess
    for deal in session.exec(select(Deal)).all():
        deal.title = "Spam"
        session.add(deal)
    pipeline = session.exec(select(Pipeline)).one()
    session.add(Stage(name="Rubbish", pipeline_id=pipeline.id, position=9))  # type: ignore[arg-type]
    arjun.full_name = "Someone else"
    chat = AgentConversation(user_id=arjun_id, title="Hi")  # type: ignore[arg-type]
    session.add(chat)
    session.flush()
    session.add(ApiToken(user_id=arjun_id, name="t", token_hash="h" * 64, prefix="df_x"))  # type: ignore[arg-type]
    session.add(
        AIUsage(
            feature="copilot",
            user_id=arjun_id,
            turn_id="t1",
            model="m",
            conversation_id=chat.id,
        )
    )
    session.commit()

    demo_data.reset(session)

    assert count(session, Deal) == deals
    assert session.exec(select(Deal).where(Deal.title == "Spam")).first() is None
    assert [s.name for s in session.exec(select(Stage).order_by(col(Stage.position))).all()] == [
        "Lead",
        "Qualified",
        "Proposal",
        "Negotiation",
    ]
    arjun = session.exec(select(User).where(User.email == "arjun@dealflow.dev")).one()
    assert arjun.id == arjun_id and arjun.full_name == "Arjun Mehta"  # still signed in
    assert count(session, AgentConversation) == 0 and count(session, ApiToken) == 0
    kept = session.exec(select(AIUsage).where(AIUsage.turn_id == "t1")).one()  # budgets hold
    assert kept.user_id == arjun_id and kept.conversation_id is None


def test_refresh_loads_then_resets_once_a_day(session):
    assert demo_data.refresh(session) == "loaded"
    assert demo_data.refresh(session) == "fresh"
    first = demo_data.loaded_on(session)
    assert first is not None
    later = first + demo_data.RESET_AFTER + timedelta(minutes=1)
    assert demo_data.refresh(session, now=later) == "reset"
    assert demo_data.loaded_on(session) > first  # type: ignore[operator]


def test_daily_job_runs_once_a_day_from_its_hour(session):
    tz = ZoneInfo("Asia/Kolkata")

    def at(day: int, hour: int) -> datetime:
        return datetime(2026, 11, day, hour, 30, tzinfo=tz).astimezone(UTC)

    assert not claim_daily_run(session, "job", 7, now=at(20, 6))  # too early
    assert claim_daily_run(session, "job", 7, now=at(20, 9))  # woke up late: runs
    assert not claim_daily_run(session, "job", 7, now=at(20, 10))  # once
    assert not claim_daily_run(session, "job", 7, now=at(21, 3))
    assert claim_daily_run(session, "job", 7, now=at(21, 7))  # the next day
