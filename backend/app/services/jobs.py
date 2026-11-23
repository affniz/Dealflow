"""Background jobs that report how they went.

Every run of a worker job is recorded in the jobrun table: when it started and finished,
what it did, and the error if it failed. Admins see this in Settings > System, a banner
tells them when something needs attention, and when a job starts failing they get an
email (if SMTP is set up). Failures are also logged with their traceback, so they reach
Sentry when that's on.

The run is recorded in its own database sessions, apart from the job's, so a job that
fails half-way and rolls back still leaves its record.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Connection, Engine
from sqlmodel import Session, col, delete, select

from app.core import logs
from app.core.config import settings
from app.core.db import engine as default_engine
from app.core.time import describe
from app.models import (
    JobHealth,
    JobRun,
    JobRunPublic,
    JobStatus,
    Role,
    SystemStatus,
    User,
    utcnow,
)
from app.services.email import send_email

log = logging.getLogger(__name__)

JOB_RUN_DAYS = 30  # how long run records are kept
# a run this old that hasn't finished most likely died with the worker
STUCK_AFTER = timedelta(hours=1)
# runs every ROTTING_CHECK_INTERVAL_SECONDS; nothing at all for this much longer than that
# means the worker isn't running
WORKER_SILENT_GRACE = timedelta(minutes=15)
FINISHED = (JobStatus.succeeded, JobStatus.warning, JobStatus.failed)


@dataclass(frozen=True)
class Job:
    name: str
    schedule: str


def jobs(ai_configured: bool) -> dict[str, Job]:
    """The worker's jobs as admins see them, in the order they're listed."""
    every = settings.ROTTING_CHECK_INTERVAL_SECONDS
    found: dict[str, Job] = {
        "pipeline_review": Job(
            "Morning pipeline review",
            f"Daily from {settings.PIPELINE_REVIEW_HOUR:02d}:00 ({settings.TIMEZONE})"
            if ai_configured
            else "Off: the AI agents aren't set up",
        ),
        "check_rotting": Job(
            "Stalled-deal check",
            "Every hour" if every == 3600 else f"Every {round(every / 60)} minutes",
        ),
        "purge_trash": Job("Trash cleanup", "Every hour"),
    }
    if settings.DEMO_MODE:
        found["demo_refresh"] = Job("Demo data reset", "Daily")
    return found


def job_name(job: str) -> str:
    known = jobs(ai_configured=True).get(job)
    return known.name if known else job.replace("_", " ").capitalize()


# ------------------------------------------------------------------ running a job


def outcome(result: dict[str, Any]) -> tuple[JobStatus, dict[str, Any], str | None]:
    """How a run went, from what the job returned: a "skipped" reason means there was
    nothing to do; a "problem" means it finished, but not all of it worked."""
    result = dict(result)
    problem = result.pop("problem", None)
    if problem:
        return JobStatus.warning, result, str(problem)
    if result.get("skipped"):
        return JobStatus.skipped, result, None
    return JobStatus.succeeded, result, None


Bind = Engine | Connection


def _session(bind: Bind) -> Session:
    # on a Connection (tests), commits become savepoints inside its transaction
    return Session(bind, join_transaction_mode="create_savepoint")


def run_job(
    job: str, work: Callable[[Session], dict[str, Any]], bind: Bind | None = None
) -> dict[str, Any]:
    """Run `work` with a session of its own, recording the run. Re-raises a failure after
    recording it, so the worker (and Sentry) sees it too."""
    eng = bind or default_engine
    with _session(eng) as s:
        run = JobRun(job=job, status=JobStatus.running)
        s.add(run)
        s.commit()
        run_id: int = run.id  # type: ignore[assignment]
    token = logs.job.set(f"{job}#{run_id}")
    try:
        log.info("Started %s", job_name(job))
        try:
            with _session(eng) as s:
                result = work(s)
        except Exception as exc:
            log.exception("%s failed", job_name(job))
            _finish(eng, run_id, JobStatus.failed, {}, f"{type(exc).__name__}: {exc}")
            raise
        status, result, error = outcome(result)
        level = logging.WARNING if status == JobStatus.warning else logging.INFO
        log.log(level, "%s: %s", job_name(job), error or status.value, extra={"result": result})
        _finish(eng, run_id, status, result, error)
        return result
    finally:
        logs.job.reset(token)


def _finish(
    eng: Bind, run_id: int, status: JobStatus, result: dict[str, Any], error: str | None
) -> None:
    with _session(eng) as s:
        run = s.get(JobRun, run_id)
        assert run is not None
        run.status = status
        run.finished_at = utcnow()
        run.result = result
        run.error = error[:2000] if error else None
        s.add(run)
        s.commit()
        if status in (JobStatus.failed, JobStatus.warning):
            alert(s, run)


def alert(session: Session, run: JobRun) -> bool:
    """Email the admins that a job has started failing. Only the first bad run in a row
    sends one: the email says what went wrong, and repeating it every hour wouldn't help."""
    previous = session.exec(
        select(JobRun)
        .where(
            JobRun.job == run.job,
            col(JobRun.status).in_(FINISHED),
            col(JobRun.started_at) < run.started_at,
        )
        .order_by(col(JobRun.started_at).desc())
    ).first()
    if previous is not None and previous.status != JobStatus.succeeded:
        return False
    admins = session.exec(
        select(User.email).where(
            col(User.role).in_([Role.owner, Role.admin]),
            col(User.is_active).is_(True),
        )
    ).all()
    name = job_name(run.job)
    what = "failed" if run.status == JobStatus.failed else "had a problem"
    app_url = (settings.APP_URL or "http://localhost:5173").rstrip("/")
    return send_email(
        list(admins),
        f"Dealflow: {name} {what}",
        f"{name} {what} on {describe(run.started_at)}:\n\n{run.error}\n\n"
        f"See what's happening at {app_url}/settings?tab=system\n\n"
        "You won't get another email about this job until it has worked again.\n",
    )


def prune(session: Session, now: datetime | None = None) -> int:
    """Delete run records older than JOB_RUN_DAYS. Commits."""
    cutoff = (now or utcnow()) - timedelta(days=JOB_RUN_DAYS)
    deleted = session.exec(delete(JobRun).where(col(JobRun.started_at) < cutoff))
    session.commit()
    return deleted.rowcount or 0  # type: ignore[attr-defined]


# ------------------------------------------------------------------ the status page


def _public(run: JobRun | None) -> JobRunPublic | None:
    return JobRunPublic.model_validate(run) if run else None


def system_status(
    session: Session, ai_configured: bool, now: datetime | None = None
) -> SystemStatus:
    now = now or utcnow()
    problems: list[str] = []
    health: list[JobHealth] = []
    for job, info in jobs(ai_configured).items():
        runs = select(JobRun).where(JobRun.job == job)
        last = session.exec(runs.order_by(col(JobRun.started_at).desc())).first()
        # a skipped run says nothing about whether the job works; look past it
        last_done = session.exec(
            runs.where(col(JobRun.status).in_(FINISHED)).order_by(col(JobRun.started_at).desc())
        ).first()
        last_success = session.exec(
            runs.where(JobRun.status == JobStatus.succeeded).order_by(col(JobRun.started_at).desc())
        ).first()
        health.append(
            JobHealth(
                job=job,
                name=info.name,
                schedule=info.schedule,
                last_run=_public(last),
                last_success_at=last_success.finished_at if last_success else None,
            )
        )
        if last is not None and last.status == JobStatus.running:
            if now - last.started_at > STUCK_AFTER:
                problems.append(
                    f"{info.name} started on {describe(last.started_at)} and never finished. "
                    "The worker may have stopped while it ran."
                )
        if last_done is not None and last_done.status != JobStatus.succeeded:
            what = "failed" if last_done.status == JobStatus.failed else "had a problem"
            problems.append(
                f"{info.name} {what} on {describe(last_done.started_at)}: {last_done.error}"
            )

    latest = session.exec(select(JobRun).order_by(col(JobRun.started_at).desc())).first()
    silent_after = timedelta(seconds=settings.ROTTING_CHECK_INTERVAL_SECONDS) + WORKER_SILENT_GRACE
    if latest is not None and now - latest.started_at > silent_after:
        problems.insert(
            0,
            f"The background worker hasn't run anything since {describe(latest.started_at)}, "
            "so stalled deals aren't being flagged and the morning review won't run. "
            "Check that it's running (see the README).",
        )
    elif latest is None and settings.ENVIRONMENT == "production":
        problems.insert(
            0,
            "The background worker hasn't run any jobs yet. If the app started more than a "
            "few minutes ago, check that it's running (see the README).",
        )
    recent = session.exec(
        select(JobRun)
        .where(JobRun.status != JobStatus.skipped)  # the hourly "nothing to do" runs
        .order_by(col(JobRun.started_at).desc())
        .limit(20)
    ).all()
    return SystemStatus(
        problems=problems,
        jobs=health,
        recent_runs=[JobRunPublic.model_validate(r) for r in recent],
        sentry=bool(settings.SENTRY_DSN),
        emails=settings.emails_enabled,
    )
