from datetime import timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func
from sqlmodel import col, select

from app.api.access import scoped
from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Deal,
    DealStatus,
    LostReason,
    LostReasonReport,
    LostReasonStat,
    Pipeline,
    PipelineSummary,
    StageSummary,
    utcnow,
)
from app.services.stats import StageTotals, money, open_totals_by_stage, weighted

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/pipeline/{pipeline_id}", response_model=PipelineSummary)
def pipeline_summary(
    session: SessionDep,
    user: CurrentUser,
    pipeline_id: int,
    owner_id: int | None = Query(None, description="Only deals owned by this user"),
    days: int | None = Query(
        None, ge=1, le=3650, description="Count won and lost deals closed in the last N days"
    ),
) -> PipelineSummary:
    """Per-stage deal counts, totals and probability-weighted forecast (open deals), plus won
    and lost totals and the win rate (all time, or the last `days`)."""
    pipeline = session.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")
    filters = [Deal.owner_id == owner_id] if owner_id is not None else []

    by_stage = open_totals_by_stage(session, user, pipeline_id, filters)
    stages = []
    for stage in pipeline.stages:
        t = by_stage.get(stage.id, StageTotals())  # type: ignore[arg-type]
        stages.append(
            StageSummary(
                stage_id=stage.id,
                name=stage.name,
                probability=stage.probability,
                deal_count=t.count,
                total_value=t.total,
                weighted_value=weighted(t.total, stage.probability),
            )
        )

    since = utcnow() - timedelta(days=days) if days else None
    closed = dict.fromkeys((DealStatus.won, DealStatus.lost), (0, None))
    stmt = scoped(select(Deal.status, func.count(), func.sum(Deal.value)), Deal, user).where(
        Deal.pipeline_id == pipeline_id, Deal.status != DealStatus.open, *filters
    )
    if since is not None:
        stmt = stmt.where(col(Deal.closed_at) >= since)
    closed.update({s: (n, total) for s, n, total in session.exec(stmt.group_by(Deal.status))})
    won, lost = closed[DealStatus.won][0], closed[DealStatus.lost][0]

    return PipelineSummary(
        pipeline_id=pipeline_id,
        name=pipeline.name,
        stages=stages,
        open_count=sum(s.deal_count for s in stages),
        open_value=money(sum(s.total_value for s in stages)),
        weighted_value=money(sum(s.weighted_value for s in stages)),
        rotting_count=sum(t.rotting for t in by_stage.values()),
        since=since,
        won_count=won,
        won_value=money(closed[DealStatus.won][1]),
        lost_count=lost,
        lost_value=money(closed[DealStatus.lost][1]),
        win_rate=round(won / (won + lost), 4) if won + lost else None,
    )


@router.get("/lost-reasons", response_model=LostReasonReport)
def lost_reasons(
    session: SessionDep,
    user: CurrentUser,
    pipeline_id: int | None = None,
    owner_id: int | None = Query(None, description="Only deals owned by this user"),
    days: int = Query(90, ge=1, le=3650, description="Look back this many days"),
) -> LostReasonReport:
    """Why deals were lost: count, value and share per reason, most common first."""
    since = utcnow() - timedelta(days=days)
    stmt = (
        scoped(
            select(LostReason.id, LostReason.label, func.count(), func.sum(Deal.value)),
            Deal,
            user,
        )
        .join(LostReason, col(LostReason.id) == Deal.lost_reason_id)
        .where(Deal.status == DealStatus.lost, col(Deal.closed_at) >= since)
        .group_by(LostReason.id, LostReason.label)
    )
    if pipeline_id is not None:
        stmt = stmt.where(Deal.pipeline_id == pipeline_id)
    if owner_id is not None:
        stmt = stmt.where(Deal.owner_id == owner_id)
    rows = session.exec(stmt).all()

    lost_count = sum(n for _, _, n, _ in rows)
    reasons = [
        LostReasonStat(
            reason_id=rid,
            label=label,
            count=n,
            value=money(total),
            share=round(n / lost_count, 4),
        )
        for rid, label, n, total in rows
    ]
    reasons.sort(key=lambda r: (-r.count, -r.value, r.label))
    return LostReasonReport(
        since=since,
        lost_count=lost_count,
        lost_value=money(sum(r.value for r in reasons)),
        reasons=reasons,
    )
