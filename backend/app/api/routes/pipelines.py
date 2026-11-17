from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import Session, col, select

from app.api.access import save
from app.api.deps import AdminUser, CurrentUser, SessionDep
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
    _get_or_404(session, Pipeline, pipeline_id)
    return save(session, Stage.model_validate(body, update={"pipeline_id": pipeline_id}))


@router.patch("/stages/{stage_id}", response_model=StagePublic)
def update_stage(session: SessionDep, _: AdminUser, stage_id: int, body: StageUpdate) -> Stage:
    stage = _get_or_404(session, Stage, stage_id)
    stage.sqlmodel_update(body.model_dump(exclude_unset=True))
    return save(session, stage)


@router.delete("/stages/{stage_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_stage(session: SessionDep, _: AdminUser, stage_id: int) -> Response:
    stage = _get_or_404(session, Stage, stage_id)
    if session.exec(select(Deal.id).where(Deal.stage_id == stage_id)).first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Move this stage's deals before deleting it")
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
