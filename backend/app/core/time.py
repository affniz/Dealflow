from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import settings


def team_tz() -> ZoneInfo:
    return ZoneInfo(settings.TIMEZONE)


def local(dt: datetime) -> datetime:
    """A UTC (or naive-as-UTC) datetime in the team's time zone."""
    return dt.astimezone(team_tz())


def describe(dt: datetime) -> str:
    """'18 Nov, 10:00 IST' in the team's time zone."""
    t = local(dt)
    return f"{t:%d %b, %H:%M} {t.tzname()}"
