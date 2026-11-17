"""Money and per-stage aggregates shared by the dashboard and the board."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func
from sqlmodel import Session, select

from app.api.access import scoped
from app.models import Deal, DealStatus, User

CENT = Decimal("0.01")


def money(x: object) -> Decimal:
    return Decimal(str(x or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


def weighted(total: Decimal, probability: int) -> Decimal:
    return money(total * probability / 100)


@dataclass
class StageTotals:
    count: int = 0
    total: Decimal = Decimal("0.00")
    rotting: int = 0


def open_totals_by_stage(session: Session, user: User, pipeline_id: int) -> dict[int, StageTotals]:
    """Open deals in a pipeline, grouped by stage, limited to what the user can see."""
    stmt = scoped(
        select(Deal.stage_id, func.count(), func.sum(Deal.value), func.count(Deal.rotting_since)),
        Deal,
        user,
    ).where(Deal.pipeline_id == pipeline_id, Deal.status == DealStatus.open)
    rows = session.exec(stmt.group_by(Deal.stage_id)).all()
    return {stage_id: StageTotals(n, money(total), rot) for stage_id, n, total, rot in rows}
