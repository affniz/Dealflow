"""Celery worker and scheduler.

Run both in one process during development:
    celery -A app.worker worker --beat --loglevel=info
"""

import logging

from celery import Celery
from celery.schedules import crontab
from celery.signals import setup_logging, worker_ready
from sqlmodel import Session

from app.agent.copilot import get_client
from app.agent.pipeline import review_stalled_deals
from app.agent.proposals import expire_stale_suggestions
from app.core.config import settings
from app.core.db import engine
from app.core.logs import setup_logging as configure_logging
from app.core.monitoring import init_sentry
from app.demo_data import refresh
from app.services import jobs
from app.services.api_tokens import purge_expired_tokens, warn_expiring
from app.services.daily import claim_daily_run
from app.services.rotting import check_rotting
from app.services.trash import purge_expired

log = logging.getLogger(__name__)

REVIEW_KEY = "pipeline_review_schedule"  # appsetting row: the last day the morning review ran


@setup_logging.connect
def _logging(**_: object) -> None:
    """Log like the API does (app.core.logs) instead of Celery's own format."""
    configure_logging()


init_sentry("worker")

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
        "token-expiry": {"task": "dealflow.token_expiry", "schedule": 3600},
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
    token_expiry_task.delay()
    pipeline_review_if_due_task.delay()


# Each task records its run (app.services.jobs), so admins can see in Settings > System
# when it last ran and whether it worked, and hear about it when it stops working.


def check_rotting_job(session: Session) -> dict[str, object]:
    result = check_rotting(session)
    # pipeline suggestions that nobody answered, or that stopped applying, expire, so their
    # deals come up for review again
    expired = expire_stale_suggestions(session)
    return {"flagged": result.flagged, "cleared": result.cleared, "suggestions_expired": expired}


def purge_trash_job(session: Session) -> dict[str, object]:
    """Delete for good what has been in the trash longer than TRASH_DAYS, old job records, and
    access tokens that expired a while ago (KEEP_EXPIRED)."""
    purged: dict[str, object] = dict(purge_expired(session))
    purged["job_runs"] = jobs.prune(session)
    purged["expired_tokens"] = purge_expired_tokens(session)
    return purged


def token_expiry_job(session: Session) -> dict[str, object]:
    """Email people a week before a token they've used stops working (app.services.api_tokens)."""
    if not settings.emails_enabled:
        return {"skipped": "Email isn't set up"}
    sent, failed = warn_expiring(session)
    if not sent and not failed:
        return {"skipped": "No tokens expiring this week"}
    result: dict[str, object] = {"emails_sent": sent}
    if failed:
        result["problem"] = (
            f"{failed} expiry email{'s' if failed > 1 else ''} couldn't be sent; "
            "they'll be tried again next hour"
        )
    return result


def demo_refresh_job(session: Session) -> dict[str, object]:
    """The public demo goes back to the sample data once a day (see app.demo_data)."""
    done = refresh(session)
    # it's asked every hour but resets once a day; the other 23 asks did nothing
    return {"demo_data": done} if done != "fresh" else {"skipped": "Reset already today"}


def pipeline_review_job(session: Session) -> dict[str, object]:
    client = get_client()
    if client is None:
        return {"skipped": "AI is not configured"}
    check_rotting(session)  # make sure the stalled flags are current first
    expired = expire_stale_suggestions(session)  # and free deals whose suggestions went stale
    s = review_stalled_deals(session, client)
    result: dict[str, object] = {
        "reviewed": s.reviewed,
        "failed": s.failed,
        "proposals": s.proposals,
    }
    if expired:
        result["suggestions_expired"] = expired
    if s.skipped_reason:
        result["skipped"] = s.skipped_reason
    problems = []
    if s.failed:
        problems.append(
            f"{s.failed} of {s.failed + s.reviewed} deal reviews failed; "
            "their errors are in the inbox's agent runs"
        )
    if s.stopped_by_budget:
        problems.append(f"it stopped early: {s.stopped_by_budget}")
    if problems:
        result["problem"] = "; ".join(problems)
    return result


@celery_app.task(name="dealflow.check_rotting")
def check_rotting_task() -> dict[str, object]:
    return jobs.run_job("check_rotting", check_rotting_job)


@celery_app.task(name="dealflow.purge_trash")
def purge_trash_task() -> dict[str, object]:
    return jobs.run_job("purge_trash", purge_trash_job)


@celery_app.task(name="dealflow.token_expiry")
def token_expiry_task() -> dict[str, object]:
    return jobs.run_job("token_expiry", token_expiry_job)


@celery_app.task(name="dealflow.demo_refresh")
def demo_refresh_task() -> dict[str, object]:
    return jobs.run_job("demo_refresh", demo_refresh_job)


@celery_app.task(name="dealflow.pipeline_review_if_due")
def pipeline_review_if_due_task() -> dict[str, object]:
    """The morning review, if it hasn't run today and it's past PIPELINE_REVIEW_HOUR.
    Asked every hour, so only a review that actually starts is recorded."""
    if get_client() is None:
        return {"skipped": "AI is not configured"}
    with Session(engine) as session:
        if not claim_daily_run(session, REVIEW_KEY, settings.PIPELINE_REVIEW_HOUR):
            return {"skipped": "Not due"}
    return pipeline_review_task()


@celery_app.task(name="dealflow.pipeline_review")
def pipeline_review_task() -> dict[str, object]:
    return jobs.run_job("pipeline_review", pipeline_review_job)
