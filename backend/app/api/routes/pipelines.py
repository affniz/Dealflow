from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import Session, col, select

from app.api.access import save
from app.api.deps import AdminUser, CurrentUser, NotInDemo, SessionDep
from app.models import (
    Deal,
    LostReason,
    LostReasonCreate,
    LostReasonPublic,
    LostReasonUpdate,
    Pipeline,
    PipelineCreate,
    PipelinePublic,
    PipelineUpdate,
    Stage,
    StageCreate,
    StageOrder,
    StagePublic,
    StageUpdate,
)

router = APIRouter(tags=["pipelines"])


def _get_or_404(session: Session, model: type, obj_id: int):  # noqa: ANN202
    obj = session.get(model, obj_id)
    if obj is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{model.__name__} not found")
    return obj


def _unique_name(session: Session, name: str, exclude_id: int | None = None) -> None:
    clash = session.exec(select(Pipeline).where(Pipeline.name == name)).first()
    if clash and clash.id != exclude_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "A pipeline with this name already exists")


@router.get("/pipelines", response_model=list[PipelinePublic])
def list_pipelines(session: SessionDep, _: CurrentUser) -> list[Pipeline]:
    return list(session.exec(select(Pipeline).order_by(col(Pipeline.id))).all())


@router.get("/pipelines/{pipeline_id}", response_model=PipelinePublic)
def read_pipeline(session: SessionDep, _: CurrentUser, pipeline_id: int) -> Pipeline:
    return _get_or_404(session, Pipeline, pipeline_id)


@router.post("/pipelines", response_model=PipelinePublic, status_code=status.HTTP_201_CREATED)
def create_pipeline(session: SessionDep, _: AdminUser, body: PipelineCreate) -> Pipeline:
    _unique_name(session, body.name)
    pipeline = Pipeline(name=body.name, rotting_days=body.rotting_days)
    pipeline.stages = [Stage(**s.model_dump()) for s in body.stages]  # pipeline_id set on flush
    return save(session, pipeline)


@router.patch("/pipelines/{pipeline_id}", response_model=PipelinePublic)
def update_pipeline(
    session: SessionDep, _: AdminUser, pipeline_id: int, body: PipelineUpdate
) -> Pipeline:
    pipeline = _get_or_404(session, Pipeline, pipeline_id)
    data = body.model_dump(exclude_unset=True)
    if "name" in data:
        _unique_name(session, data["name"], pipeline_id)
    pipeline.sqlmodel_update(data)
    return save(session, pipeline)


@router.post(
    "/pipelines/{pipeline_id}/stages",
    response_model=StagePublic,
    status_code=status.HTTP_201_CREATED,
)
def add_stage(session: SessionDep, _: AdminUser, pipeline_id: int, body: StageCreate) -> Stage:
    pipeline = _get_or_404(session, Pipeline, pipeline_id)
    update: dict[str, int] = {"pipeline_id": pipeline_id}
    if "position" not in body.model_fields_set:  # a new stage goes at the end
        update["position"] = max((s.position for s in pipeline.stages), default=-1) + 1
    return save(session, Stage.model_validate(body, update=update))


@router.put("/pipelines/{pipeline_id}/stage-order", response_model=PipelinePublic)
def reorder_stages(
    session: SessionDep, _: AdminUser, pipeline_id: int, body: StageOrder
) -> Pipeline:
    """Put the pipeline's stages in this order (positions become 0, 1, 2, ...)."""
    pipeline = _get_or_404(session, Pipeline, pipeline_id)
    stages = {s.id: s for s in pipeline.stages}
    if sorted(body.stage_ids) != sorted(stages):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "List every stage of this pipeline exactly once"
        )
    for position, stage_id in enumerate(body.stage_ids):
        stages[stage_id].position = position
        session.add(stages[stage_id])
    session.commit()
    session.refresh(pipeline)
    session.expire(pipeline, ["stages"])  # reload them in the new order
    return pipeline


@router.patch("/stages/{stage_id}", response_model=StagePublic)
def update_stage(session: SessionDep, _: AdminUser, stage_id: int, body: StageUpdate) -> Stage:
    stage = _get_or_404(session, Stage, stage_id)
    stage.sqlmodel_update(body.model_dump(exclude_unset=True))
    return save(session, stage)


# in the demo, an emptied and deleted stage would vanish from everyone's board until the reset
@router.delete(
    "/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[NotInDemo]
)
def delete_stage(session: SessionDep, _: AdminUser, stage_id: int) -> Response:
    stage = _get_or_404(session, Stage, stage_id)
    if session.exec(select(Deal.id).where(Deal.stage_id == stage_id)).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Move this stage's deals before deleting it")
    in_trash = (
        select(Deal.id).where(Deal.stage_id == stage_id).execution_options(include_deleted=True)
    )
    if session.exec(in_trash).first() is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Deleted deals in Recently deleted are still in this stage: restore and move them, "
            "or delete them for good, first",
        )
    session.delete(stage)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/lost-reasons", response_model=list[LostReasonPublic], tags=["lost reasons"])
def list_lost_reasons(
    session: SessionDep, _: CurrentUser, include_inactive: bool = False
) -> list[LostReason]:
    stmt = select(LostReason).order_by(col(LostReason.id))
    if not include_inactive:
        stmt = stmt.where(col(LostReason.is_active).is_(True))
    return list(session.exec(stmt).all())


@router.post(
    "/lost-reasons",
    response_model=LostReasonPublic,
    status_code=status.HTTP_201_CREATED,
    tags=["lost reasons"],
)
def create_lost_reason(session: SessionDep, _: AdminUser, body: LostReasonCreate) -> LostReason:
    if session.exec(select(LostReason).where(LostReason.label == body.label)).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "This lost reason already exists")
    return save(session, LostReason.model_validate(body))


@router.patch("/lost-reasons/{reason_id}", response_model=LostReasonPublic, tags=["lost reasons"])
def update_lost_reason(
    session: SessionDep, _: AdminUser, reason_id: int, body: LostReasonUpdate
) -> LostReason:
    reason = _get_or_404(session, LostReason, reason_id)
    reason.sqlmodel_update(body.model_dump(exclude_unset=True))
    return save(session, reason)
