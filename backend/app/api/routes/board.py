from fastapi import APIRouter, HTTPException, Query, status
from sqlmodel import col, select

from app.api.access import scoped
from app.api.deps import CurrentUser, SessionDep
from app.models import Board, BoardColumn, Deal, DealPublic, DealStatus, Pipeline, StagePublic
from app.services.stats import StageTotals, money, open_totals_by_stage, weighted

router = APIRouter(tags=["board"])


@router.get("/pipelines/{pipeline_id}/board", response_model=Board)
def pipeline_board(
    session: SessionDep,
    user: CurrentUser,
    pipeline_id: int,
    deals_per_stage: int = Query(50, ge=0, le=200),
) -> Board:
    """Kanban view: one column per stage with its open deals, totals and weighted forecast.

    Column totals cover every open deal in the stage, even when the deal list is capped.
    """
    pipeline = session.get(Pipeline, pipeline_id)
    if pipeline is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pipeline not found")

    by_stage = open_totals_by_stage(session, user, pipeline_id)
    columns = []
    for stage in pipeline.stages:
        t = by_stage.get(stage.id, StageTotals())  # type: ignore[arg-type]
        deals = []
        if deals_per_stage and t.count:
            deals = session.exec(
                scoped(select(Deal), Deal, user)
                .where(Deal.stage_id == stage.id, Deal.status == DealStatus.open)
                .order_by(col(Deal.created_at).desc(), col(Deal.id).desc())
                .limit(deals_per_stage)
            ).all()
        columns.append(
            BoardColumn(
                stage=StagePublic.model_validate(stage),
                deal_count=t.count,
                total_value=t.total,
                weighted_value=weighted(t.total, stage.probability),
                rotting_count=t.rotting,
                deals=[DealPublic.model_validate(d) for d in deals],
            )
        )

    return Board(
        pipeline_id=pipeline_id,
        name=pipeline.name,
        rotting_days=pipeline.rotting_days,
        columns=columns,
        total_value=money(sum(c.total_value for c in columns)),
        weighted_value=money(sum(c.weighted_value for c in columns)),
    )
