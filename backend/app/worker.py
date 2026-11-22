"""Celery worker and scheduler.

Run both in one process during development:
    celery -A app.worker worker --beat --loglevel=info
"""

import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import worker_ready
from sqlmodel import Session

from app.agent.copilot import get_client
from app.agent.pipeline import review_stalled_deals
from app.core.config import settings
from app.core.db import engine
from app.demo_data import refresh
from app.services.daily import claim_daily_run
from app.services.rotting import check_rotting
from app.services.trash import purge_expired

log = logging.getLogger(__name__)

REVIEW_KEY = "pipeline_review_schedule"  # appsetting row: the last day the morning review ran

celery_app = Celery("dealflow", broker=settings.REDIS_URL)
celery_app.conf.update(
    timezone=settings.TIMEZONE,  # crontab hours below are the team's local time
    task_ignore_result=True,
    beat_schedule={
        "check-rotting-deals": {
            "task": "dealflow.check_rotting",
            "schedule": settings.ROTTING_CHECK_INTERVAL_SECONDS,
        },
        "purge-trash": {"task": "dealflow.purge_trash", "schedule": 3600},
        # every hour, but it only runs once a day, from PIPELINE_REVIEW_HOUR on (see
        # app.services.daily): a host that slept through that hour runs it when it wakes
        "pipeline-review": {
            "task": "dealflow.pipeline_review_if_due",
            "schedule": crontab(minute=0),
        },
    },
)
if settings.DEMO_MODE:
    celery_app.conf.beat_schedule["demo-refresh"] = {
        "task": "dealflow.demo_refresh",
        "schedule": 3600,
    }


@worker_ready.connect
def catch_up(**_: object) -> None:
    """Beat doesn't run what came due while the host was asleep, so do it now."""
    check_rotting_task.delay()
    purge_trash_task.delay()
    pipeline_review_if_due_task.delay()


@celery_app.task(name="dealflow.check_rotting")
def check_rotting_task() -> dict[str, int]:
    with Session(engine) as session:
        result = check_rotting(session)
    return {"flagged": result.flagged, "cleared": result.cleared}


@celery_app.task(name="dealflow.purge_trash")
def purge_trash_task() -> dict[str, int]:
    """Delete for good what has been in the trash longer than TRASH_DAYS."""
    with Session(engine) as session:
        return purge_expired(session)


@celery_app.task(name="dealflow.pipeline_review_if_due")
def pipeline_review_if_due_task() -> dict[str, object]:
    """The morning review, if it hasn't run today and it's past PIPELINE_REVIEW_HOUR."""
    if get_client() is None:
        return {"skipped": "AI is not configured"}
    with Session(engine) as session:
        if not claim_daily_run(session, REVIEW_KEY, settings.PIPELINE_REVIEW_HOUR):
            return {"skipped": "Not due"}
    return pipeline_review_task()


@celery_app.task(name="dealflow.demo_refresh")
def demo_refresh_task() -> dict[str, str]:
    """The public demo goes back to the sample data once a day (see app.demo_data)."""
    with Session(engine) as session:
        return {"demo_data": refresh(session)}


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
