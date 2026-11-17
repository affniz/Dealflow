from decimal import ROUND_HALF_UP, Decimal

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import func
from sqlmodel import select

from app.api.access import scoped
from app.api.deps import CurrentUser, SessionDep
from app.models import Deal, DealStatus, Pipeline, PipelineSummary, StageSummary

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

CENT = Decimal("0.01")


def _money(x: object) -> Decimal:
    return Decimal(str(x or 0)).quantize(CENT, rounding=ROUND_HALF_UP)


@router.get("/pipeline/{pipeline_id}", response_model=PipelineSummary)
def pipeline_summary(session: SessionDep, user: CurrentUser, pipeline_id: int) -> PipelineSummary:
    """Per-stage deal counts, totals and probability-weighted forecast (open deals only)."""
    pipeline = session.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")

    base = scoped(select(Deal), Deal, user).where(Deal.pipeline_id == pipeline_id).subquery()
    rows = session.exec(
        select(base.c.stage_id, base.c.status, func.count(), func.sum(base.c.value)).group_by(
            base.c.stage_id, base.c.status
        )
    ).all()

    open_by_stage: dict[int, tuple[int, Decimal]] = {}
    won_count, won_value, lost_count = 0, Decimal(0), 0
    for stage_id, deal_status, count, total in rows:
        # DealStatus is a str enum, so this matches whether the driver returns str or enum
        if deal_status == DealStatus.open:
            prev_count, prev_total = open_by_stage.get(stage_id, (0, Decimal(0)))
            open_by_stage[stage_id] = (prev_count + count, prev_total + _money(total))
        elif deal_status == DealStatus.won:
            won_count += count
            won_value += _money(total)
        else:
            lost_count += count

    stages = []
    for stage in sorted(pipeline.stages, key=lambda s: s.position):
        count, total = open_by_stage.get(stage.id, (0, Decimal(0)))  # type: ignore[arg-type]
        stages.append(
            StageSummary(
                stage_id=stage.id,  # type: ignore[arg-type]
                name=stage.name,
                probability=stage.probability,
                deal_count=count,
                total_value=_money(total),
                weighted_value=_money(total * stage.probability / 100),
            )
        )

    return PipelineSummary(
        pipeline_id=pipeline_id,
        name=pipeline.name,
        stages=stages,
        open_count=sum(s.deal_count for s in stages),
        open_value=_money(sum(s.total_value for s in stages)),
        weighted_value=_money(sum(s.weighted_value for s in stages)),
        won_count=won_count,
        won_value=_money(won_value),
        lost_count=lost_count,
    )
