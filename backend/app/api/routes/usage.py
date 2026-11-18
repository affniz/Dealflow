import re

from fastapi import APIRouter, HTTPException, Query, status

from app.agent import usage
from app.api.deps import AdminUser, CurrentUser, SessionDep
from app.models import MyUsage, UsageSummary

router = APIRouter(prefix="/usage", tags=["usage"])

MonthQuery = Query(None, description="YYYY-MM in the team's time zone; default this month")


def _check(month: str | None) -> str | None:
    if month is not None and not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "month must look like 2026-11")
    return month


@router.get("/me", response_model=MyUsage)
def my_usage(session: SessionDep, user: CurrentUser, month: str | None = MonthQuery) -> MyUsage:
    """What the signed-in user's Copilot questions cost this month."""
    return usage.my_usage(session, user, _check(month))


@router.get("/summary", response_model=UsageSummary)
def usage_summary(
    session: SessionDep, _: AdminUser, month: str | None = MonthQuery
) -> UsageSummary:
    """AI spend for the month by feature, model, person and day (admins only)."""
    return usage.summary(session, _check(month))
