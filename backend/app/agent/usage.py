"""Recording what every Claude call used and cost, and summing it up."""

from decimal import Decimal
from typing import Any

from sqlalchemy import Date, cast, func
from sqlalchemy import inspect as sa_inspect
from sqlmodel import Session, col, select

from app.agent.pricing import PRICES_AS_OF, cost_usd
from app.core.time import month_bounds, team_tz
from app.models import (
    AIUsage,
    DailyUsage,
    FeatureUsage,
    ModelUsage,
    MyUsage,
    NamedRef,
    UsageSummary,
    UsageTotals,
    User,
    UserUsage,
)
from app.services import budgets
from app.services.names import user_name

# usage.iterations entries that are model calls (compaction/advisor aren't used here)
_MODEL_ITERATIONS = {"message", "fallback_message"}


def records_from_response(response: Any, **link: Any) -> list[AIUsage]:
    """Ledger rows for one response: one per model that ran (a fallback adds a second)."""
    usage = response.usage
    parts = [it for it in (usage.iterations or []) if it.type in _MODEL_ITERATIONS] or [usage]
    rows = []
    for part in parts:
        model = getattr(part, "model", None) or response.model
        cache = part.cache_creation
        write_5m = (
            cache.ephemeral_5m_input_tokens if cache else (part.cache_creation_input_tokens or 0)
        )
        write_1h = cache.ephemeral_1h_input_tokens if cache else 0
        read = part.cache_read_input_tokens or 0
        rows.append(
            AIUsage(
                model=model,
                request_id=getattr(response, "_request_id", None),
                input_tokens=part.input_tokens,
                cache_read_tokens=read,
                cache_write_tokens=write_5m + write_1h,
                output_tokens=part.output_tokens,
                cost_usd=cost_usd(
                    model,
                    input_tokens=part.input_tokens,
                    output_tokens=part.output_tokens,
                    cache_read_tokens=read,
                    cache_write_5m_tokens=write_5m,
                    cache_write_1h_tokens=write_1h,
                ),
                **link,
            )
        )
    return rows


def persist_after_failure(session: Session, rows: list[AIUsage], **overrides: Any) -> None:
    """A failed turn's database work is rolled back, but its calls were still billed: write
    fresh copies of their ledger rows after the rollback. Rows already committed (the Copilot
    commits before each model call) are kept as they are."""
    for row in rows:
        if sa_inspect(row).persistent:
            continue
        data = row.model_dump(exclude={"id"})
        data.update(overrides)
        session.add(AIUsage(**data))
    session.commit()


# ---------------------------------------------------------------- summaries


def _money(x: Any) -> Decimal:
    return Decimal(str(x or 0)).quantize(Decimal("0.0001"))


def _totals_cols() -> list[Any]:
    return [
        func.coalesce(func.sum(AIUsage.cost_usd), 0),
        func.count(),
        func.count(func.distinct(AIUsage.turn_id)),
        func.coalesce(func.sum(AIUsage.input_tokens), 0),
        func.coalesce(func.sum(AIUsage.cache_read_tokens), 0),
        func.coalesce(func.sum(AIUsage.cache_write_tokens), 0),
        func.coalesce(func.sum(AIUsage.output_tokens), 0),
    ]


def _totals(row: Any) -> dict[str, Any]:
    cost, calls, units, inp, read, write, out = row
    return {
        "cost_usd": _money(cost),
        "calls": calls,
        "units": units,
        "input_tokens": inp,
        "cache_read_tokens": read,
        "cache_write_tokens": write,
        "output_tokens": out,
    }


def summary(session: Session, month: str | None) -> UsageSummary:
    label, start, end = month_bounds(month)
    in_month = (col(AIUsage.created_at) >= start, col(AIUsage.created_at) < end)

    total = UsageTotals(**_totals(session.exec(select(*_totals_cols()).where(*in_month)).one()))

    by_feature = []
    for row in session.exec(
        select(AIUsage.feature, *_totals_cols()).where(*in_month).group_by(AIUsage.feature)
    ).all():
        t = _totals(row[1:])
        avg = (t["cost_usd"] / t["units"]).quantize(Decimal("0.0001")) if t["units"] else None
        by_feature.append(FeatureUsage(feature=row[0], avg_cost_per_unit=avg, **t))

    by_model = [
        ModelUsage(model=row[0], **_totals(row[1:]))
        for row in session.exec(
            select(AIUsage.model, *_totals_cols()).where(*in_month).group_by(AIUsage.model)
        ).all()
    ]

    per_user: dict[int | None, dict[str, Any]] = {}
    for user_id, feature, cost, questions in session.exec(
        select(
            AIUsage.user_id,
            AIUsage.feature,
            func.coalesce(func.sum(AIUsage.cost_usd), 0),
            func.count(func.distinct(AIUsage.turn_id)),
        )
        .where(*in_month)
        .group_by(col(AIUsage.user_id), col(AIUsage.feature))
    ).all():
        entry = per_user.setdefault(
            user_id, {"copilot": Decimal(0), "pipeline": Decimal(0), "questions": 0}
        )
        if feature == "copilot":
            entry["copilot"] += _money(cost)
            entry["questions"] += questions
        else:
            entry["pipeline"] += _money(cost)
    users = {
        u.id: u
        for u in session.exec(select(User).where(col(User.id).in_([k for k in per_user if k])))
    }
    by_user = [
        UserUsage(
            user=NamedRef(id=uid, name=user_name(users[uid]))
            if uid is not None and uid in users
            else None,
            copilot_cost_usd=v["copilot"],
            pipeline_cost_usd=v["pipeline"],
            copilot_questions=v["questions"],
        )
        for uid, v in per_user.items()
    ]
    by_user.sort(key=lambda u: -(u.copilot_cost_usd + u.pipeline_cost_usd))

    local_day = cast(func.timezone(team_tz().key, AIUsage.created_at), Date)
    daily = [
        DailyUsage(date=day, cost_usd=_money(cost))
        for day, cost in session.exec(
            select(local_day, func.coalesce(func.sum(AIUsage.cost_usd), 0))
            .where(*in_month)
            .group_by(local_day)
            .order_by(local_day)
        ).all()
    ]
    unpriced = session.exec(
        select(func.count()).where(*in_month, col(AIUsage.cost_usd).is_(None))
    ).one()

    return UsageSummary(
        month=label,
        prices_as_of=PRICES_AS_OF,
        total=total,
        by_feature=sorted(by_feature, key=lambda f: f.feature),
        by_model=sorted(by_model, key=lambda m: -m.cost_usd),
        by_user=by_user,
        daily=daily,
        unpriced_calls=unpriced,
        **_budget_fields(session, label),
    )


def _budget_fields(session: Session, label: str) -> dict[str, Any]:
    """Budgets only apply to the current month."""
    if label != month_bounds(None)[0]:
        return {}
    limits = budgets.get_budgets(session)
    return {
        "copilot_budget_per_person_usd": limits.copilot_per_person_usd,
        "pipeline_budget": budgets.status(
            budgets.pipeline_spent(session), limits.pipeline_team_usd
        ),
    }


def my_usage(session: Session, user: User, month: str | None) -> MyUsage:
    label, start, end = month_bounds(month)
    cost, questions = session.exec(
        select(
            func.coalesce(func.sum(AIUsage.cost_usd), 0),
            func.count(func.distinct(AIUsage.turn_id)),
        ).where(
            AIUsage.user_id == user.id,
            AIUsage.feature == "copilot",
            col(AIUsage.created_at) >= start,
            col(AIUsage.created_at) < end,
        )
    ).one()
    budget = budgets.get_budgets(session).copilot_per_person_usd if month is None else None
    return MyUsage(
        month=label,
        cost_usd=_money(cost),
        questions=questions,
        budget_usd=budget,
        budget_used_pct=budgets.used_pct(Decimal(str(cost)), budget),
        resets_on=budgets.resets_on() if month is None else None,
    )
