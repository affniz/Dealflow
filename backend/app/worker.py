"""Celery worker and scheduler.

Run both in one process during development:
    celery -A app.worker worker --beat --loglevel=info
"""

import logging

from celery import Celery
from celery.schedules import crontab
from sqlmodel import Session

from app.agent.copilot import get_client
from app.agent.pipeline import review_stalled_deals
from app.core.config import settings
from app.core.db import engine
from app.services.rotting import check_rotting

log = logging.getLogger(__name__)

celery_app = Celery("dealflow", broker=settings.REDIS_URL)
celery_app.conf.update(
    timezone=settings.TIMEZONE,  # crontab hours below are the team's local time
    task_ignore_result=True,
    beat_schedule={
        "check-rotting-deals": {
            "task": "dealflow.check_rotting",
            "schedule": settings.ROTTING_CHECK_INTERVAL_SECONDS,
        },
        "pipeline-review": {
            "task": "dealflow.pipeline_review",
            "schedule": crontab(hour=settings.PIPELINE_REVIEW_HOUR, minute=0),
        },
    },
)


@celery_app.task(name="dealflow.check_rotting")
def check_rotting_task() -> dict[str, int]:
    with Session(engine) as session:
        result = check_rotting(session)
    return {"flagged": result.flagged, "cleared": result.cleared}


@celery_app.task(name="dealflow.pipeline_review")
def pipeline_review_task() -> dict[str, object]:
    client = get_client()
    if client is None:
        log.info("Pipeline review skipped: ANTHROPIC_API_KEY isn't set")
        return {"skipped": "AI is not configured"}
    with Session(engine) as session:
        check_rotting(session)  # make sure the stalled flags are current first
        s = review_stalled_deals(session, client)
    return {
        "reviewed": s.reviewed,
        "failed": s.failed,
        "proposals": s.proposals,
        "skipped": s.skipped_reason,
        "stopped_by_budget": s.stopped_by_budget,
    }
