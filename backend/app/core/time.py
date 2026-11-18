from datetime import UTC, datetime, timedelta
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


def month_bounds(month: str | None) -> tuple[str, datetime, datetime]:
    """'YYYY-MM' (default: this month) in the team's time zone, as UTC start/end."""
    tz = team_tz()
    if month:
        year, mon = (int(x) for x in month.split("-"))
        start = datetime(year, mon, 1, tzinfo=tz)
    else:
        now = local(datetime.now(UTC))
        start = datetime(now.year, now.month, 1, tzinfo=tz)
    end = (start + timedelta(days=32)).replace(day=1)
    return f"{start:%Y-%m}", start, end
