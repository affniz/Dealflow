"""Once-a-day jobs on a host that may be asleep when they're due.

A free Render service sleeps after 15 idle minutes, and the scheduler sleeps with it, so a job
set for 07:00 would only run on mornings someone happened to be using the app. Instead, the
worker asks "has today's run happened yet?" every hour and as soon as it wakes up, and
claim_daily_run() answers yes exactly once per day.
"""

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from app.core.time import local
from app.models import AppSetting, utcnow


def claim_daily_run(session: Session, key: str, hour: int, now: datetime | None = None) -> bool:
    """True the first time it's asked on a day (team time), from `hour` o'clock on.

    The day is recorded in the appsetting table under `key`, with the row locked while it's
    checked, so two workers asking at once can't both get True."""
    today = local(now or utcnow())
    if today.hour < hour:
        return False
    session.exec(insert(AppSetting).values(key=key, value={}).on_conflict_do_nothing())  # type: ignore[call-overload]
    row = session.exec(
        select(AppSetting)
        .where(AppSetting.key == key)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    day = today.date().isoformat()
    if row.value.get("last_day") == day:
        session.commit()  # releases the lock
        return False
    row.value = {"last_day": day}
    row.updated_at = utcnow()
    session.add(row)
    session.commit()
    return True
