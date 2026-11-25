"""Rotting deals: open deals that have sat in one stage longer than their pipeline allows.

check_rotting() is idempotent. Each run:
  - flags newly stale deals (sets rotting_since), logs a "rotting" timeline event and
    creates a follow-up task for the deal's owner;
  - clears the flag on deals that are no longer stale (e.g. rotting_days was raised).
Deals also lose the flag immediately when they move stage or close (see routes/deals.py).
"""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, not_, or_
from sqlmodel import Session, col, select

from app.models import Activity, ActivityType, Deal, DealEvent, DealStatus, Pipeline, utcnow

# Activity.via of the generic reminder this job adds. Agents treat it as a nudge, not a plan.
AUTO_REMINDER = "auto_reminder"


@dataclass
class RottingResult:
    flagged: int
    cleared: int


def _is_stale(now: datetime):  # noqa: ANN202
    return Deal.stage_changed_at + func.make_interval(0, 0, 0, Pipeline.rotting_days) < now


def check_rotting(session: Session, now: datetime | None = None) -> RottingResult:
    now = now or utcnow()

    newly_stale = session.exec(
        select(Deal, Pipeline)
        .join(Pipeline, col(Pipeline.id) == Deal.pipeline_id)
        .where(Deal.status == DealStatus.open, col(Deal.rotting_since).is_(None), _is_stale(now))
        # another worker running at the same moment skips rows we hold, so no double tasks
        .with_for_update(skip_locked=True, of=Deal)
    ).all()
    for deal, pipeline in newly_stale:
        days = (now - deal.stage_changed_at).days
        deal.rotting_since = now
        session.add(deal)
        session.add(
            DealEvent(
                deal_id=deal.id,  # type: ignore[arg-type]
                kind="rotting",
                data={
                    "stage_id": deal.stage_id,
                    "days_in_stage": days,
                    "rotting_days": pipeline.rotting_days,
                },
            )
        )
        session.add(
            Activity(
                type=ActivityType.task,
                subject=f"Stalled deal: {deal.title}"[:255],
                body=f"No stage change in {days} days. Follow up, or move it to the right stage.",
                due_at=now,
                deal_id=deal.id,
                contact_id=deal.contact_id,
                company_id=deal.company_id,
                owner_id=deal.owner_id,
                via=AUTO_REMINDER,
            )
        )

    recovered = session.exec(
        select(Deal)
        .join(Pipeline, col(Pipeline.id) == Deal.pipeline_id)
        .where(
            col(Deal.rotting_since).is_not(None),
            or_(col(Deal.status) != DealStatus.open, not_(_is_stale(now))),
        )
        .with_for_update(skip_locked=True, of=Deal)
    ).all()
    for deal in recovered:
        deal.rotting_since = None
        session.add(deal)

    session.commit()
    return RottingResult(flagged=len(newly_stale), cleared=len(recovered))
