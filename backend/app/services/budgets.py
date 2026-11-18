"""Monthly AI budgets: a Copilot limit per person and a team limit for the pipeline agent.

Limits are checked before every model call, so a question or a deal review can go over by at
most one call. Months are calendar months in the team's time zone. Calls to models missing from
the price table have no cost and don't count.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlmodel import Session, col, select

from app.core.config import settings
from app.core.time import month_bounds
from app.models import AIUsage, AppSetting, Budgets, BudgetStatus, User, utcnow

KEY = "budgets"
WARN_AT_PCT = 80


class BudgetExceeded(Exception):
    """Raised before a model call that the budget no longer allows."""


def get_budgets(session: Session) -> Budgets:
    defaults: dict[str, Any] = {
        "copilot_per_person_usd": settings.COPILOT_MONTHLY_BUDGET_USD,
        "pipeline_team_usd": settings.PIPELINE_MONTHLY_BUDGET_USD,
    }
    stored = session.get(AppSetting, KEY)
    return Budgets(**{**defaults, **(stored.value if stored else {})})


def update_budgets(session: Session, user: User, body: Budgets) -> Budgets:
    # every field is sent: None means "no limit", not "unchanged"
    value = {k: (str(v) if v is not None else None) for k, v in body.model_dump().items()}
    stored = session.get(AppSetting, KEY) or AppSetting(key=KEY, value={})
    stored.value = value
    stored.updated_at = utcnow()
    stored.updated_by_id = user.id
    session.add(stored)
    session.commit()
    return get_budgets(session)


def _month() -> tuple[datetime, datetime]:
    _, start, end = month_bounds(None)
    return start, end


def resets_on() -> date:
    return _month()[1].date()


def _spent(session: Session, *where: Any) -> Decimal:
    start, end = _month()
    total = session.exec(
        select(func.coalesce(func.sum(AIUsage.cost_usd), 0)).where(
            col(AIUsage.created_at) >= start, col(AIUsage.created_at) < end, *where
        )
    ).one()
    return Decimal(str(total))


def copilot_spent(session: Session, user_id: int) -> Decimal:
    return _spent(session, AIUsage.feature == "copilot", AIUsage.user_id == user_id)


def pipeline_spent(session: Session) -> Decimal:
    return _spent(session, AIUsage.feature == "pipeline_agent")


def used_pct(spent: Decimal, budget: Decimal | None) -> int | None:
    if budget is None:
        return None
    if budget <= 0:
        return 100
    return int(spent * 100 / budget)


def status(spent: Decimal, budget: Decimal | None) -> BudgetStatus:
    return BudgetStatus(
        budget_usd=budget,
        spent_usd=spent.quantize(Decimal("0.0001")),
        used_pct=used_pct(spent, budget),
    )


def _reset_text() -> str:
    day = resets_on()
    return f"It resets on {day.day} {day:%B}."


def copilot_block_reason(session: Session, user: User) -> str | None:
    """Why this person can't make another Copilot call this month, or None."""
    budget = get_budgets(session).copilot_per_person_usd
    if budget is None or copilot_spent(session, user.id) < budget:  # type: ignore[arg-type]
        return None
    return (
        f"You've used your Copilot budget for this month (${budget:,.2f}). {_reset_text()} "
        "An admin can raise it in Settings."
    )


def pipeline_block_reason(session: Session) -> str | None:
    budget = get_budgets(session).pipeline_team_usd
    if budget is None or pipeline_spent(session) < budget:
        return None
    return f"The pipeline agent's monthly budget (${budget:,.2f}) is used up. {_reset_text()}"
