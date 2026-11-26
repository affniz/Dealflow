"""Logs, request IDs, error reports, the health check and background job monitoring."""

import json
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import col, select

from app import main, worker
from app.api.routes import client_errors
from app.core import logs, monitoring
from app.core.config import settings
from app.models import JobRun, JobStatus, Role, User, utcnow
from app.services import jobs
from tests.conftest import API

# ------------------------------------------------------------------ requests


def test_every_request_gets_an_id_and_a_log_line(client, login, caplog):
    h = login(Role.agent)
    caplog.set_level(logging.INFO, logger="app.requests")
    r = client.get(f"{API}/deals", headers=h, params={"q": "secret search"})
    rid = r.headers["X-Request-ID"]
    [line] = [r for r in caplog.records if r.name == "app.requests" and r.request_id == rid]
    assert line.getMessage() == f"GET {API}/deals 200"  # no query string
    assert line.request_id == rid
    assert line.status == 200 and line.duration_ms >= 0
    assert line.user_id == client.get(f"{API}/users/me", headers=h).json()["id"]

    # an ID from a proxy in front is kept; anything odd is replaced
    kept = client.get("/health", headers={"X-Request-ID": "rndr-abc12345"})
    assert kept.headers["X-Request-ID"] == "rndr-abc12345"
    odd = client.get("/health", headers={"X-Request-ID": "<script>"})
    assert odd.headers["X-Request-ID"] != "<script>"


def test_a_crash_answers_with_a_reference_not_the_error(session):
    @main.app.get("/api/v1/_boom")
    def boom() -> None:
        raise RuntimeError("database password is hunter2")

    try:
        with TestClient(main.app, raise_server_exceptions=False) as c:
            r = c.get("/api/v1/_boom")
    finally:
        main.app.router.routes.pop()
    assert r.status_code == 500
    rid = r.headers["X-Request-ID"]
    assert r.json()["detail"].endswith(f"mention reference {rid}.")
    assert "hunter2" not in r.text


def test_health_checks_the_database(client, monkeypatch):
    assert client.get("/health").json() == {"status": "ok"}
    monkeypatch.setattr(
        main, "engine", create_engine("postgresql+psycopg://nobody@127.0.0.1:1/none")
    )
    r = client.get("/health")
    assert r.status_code == 503 and r.json() == {"status": "database unreachable"}


# ------------------------------------------------------------------ log format


def make_record(**extra):  # noqa: ANN003, ANN201
    try:
        raise ValueError("bad")
    except ValueError:
        import sys

        record = logging.LogRecord("app.x", logging.ERROR, __file__, 1, "Oops %s", ("!",), None)
        record.exc_info = sys.exc_info()
    for k, v in extra.items():
        setattr(record, k, v)
    logs.ContextFilter().filter(record)
    return record


def test_json_and_text_lines():
    token = logs.request_id.set("abc123")
    try:
        record = make_record(duration_ms=12)
    finally:
        logs.request_id.reset(token)
    line = json.loads(logs.JsonFormatter().format(record))
    assert line["message"] == "Oops !" and line["level"] == "ERROR"
    assert line["request_id"] == "abc123" and line["duration_ms"] == 12
    assert "ValueError: bad" in line["exception"] and "job" not in line
    text = logs.TextFormatter().format(record)
    first, rest = text.split("\n", 1)
    assert first.endswith("app.x: Oops !  [request_id=abc123 duration_ms=12]")
    assert "ValueError: bad" in rest


def test_setup_logging_can_run_twice(monkeypatch, caplog):
    root = logging.getLogger()
    root.addHandler(logging.StreamHandler())  # as the MCP SDK's logging.basicConfig does
    logs.setup_logging()
    logs.setup_logging()
    others = [h for h in root.handlers if not type(h).__module__.startswith("_pytest")]
    assert len(others) == 1 and getattr(others[0], "dealflow", False)
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    assert settings.log_format == "json"


def test_sentry_sends_nothing_personal(monkeypatch):
    import sentry_sdk

    assert monitoring.init_sentry("api") is False  # off without a DSN
    calls = []
    monkeypatch.setattr(sentry_sdk, "init", lambda **kw: calls.append(kw))
    monkeypatch.setattr(sentry_sdk, "set_tag", lambda *a: None)
    monkeypatch.setattr(settings, "SENTRY_DSN", "https://key@o1.ingest.sentry.io/1")
    assert monitoring.init_sentry("worker") is True
    [kw] = calls
    assert kw["send_default_pii"] is False and kw["max_request_body_size"] == "never"
    assert kw["server_name"] == "worker"


# ------------------------------------------------------------------ browser errors


def test_browser_errors_are_logged_and_limited(client, caplog, monkeypatch):
    monkeypatch.setattr(client_errors, "_recent", client_errors.defaultdict(client_errors.deque))
    caplog.set_level(logging.ERROR, logger="app.browser")
    body = {"message": "x is undefined", "stack": "at Board", "path": "/board"}
    for _ in range(client_errors.PER_MINUTE + 3):
        assert client.post(f"{API}/client-errors", json=body).status_code == 204
    reports = [r for r in caplog.records if r.name == "app.browser"]
    assert len(reports) == client_errors.PER_MINUTE
    assert reports[0].getMessage() == "Browser error on /board: x is undefined"
    assert reports[0].stack == "at Board"
    too_long = {**body, "message": "x" * 1001}
    assert client.post(f"{API}/client-errors", json=too_long).status_code == 422


# ------------------------------------------------------------------ background jobs


@pytest.fixture
def bind(session):  # noqa: ANN001, ANN201
    """Job runs recorded inside the test's transaction (rolled back afterwards)."""
    return session.connection()


def runs(session, job):  # noqa: ANN001, ANN201
    return session.exec(select(JobRun).where(JobRun.job == job).order_by(col(JobRun.id))).all()


def test_a_job_run_is_recorded(session, bind):
    result = jobs.run_job("check_rotting", worker.check_rotting_job, bind=bind)
    assert result == {"flagged": 0, "cleared": 0, "suggestions_expired": 0}
    [run] = runs(session, "check_rotting")
    assert run.status == JobStatus.succeeded and run.finished_at >= run.started_at
    assert run.result == result and run.error is None


def test_failures_are_recorded_and_emailed_once(session, bind, smtp, login, caplog):
    smtp.enable()
    login(Role.admin, email="ops@example.com")
    login(Role.agent, email="rep@example.com")

    def broken(_):  # noqa: ANN001, ANN202
        raise RuntimeError("Redis went away")

    for _ in range(2):
        with pytest.raises(RuntimeError):
            jobs.run_job("purge_trash", broken, bind=bind)
    first, second = runs(session, "purge_trash")
    assert first.status == second.status == JobStatus.failed
    assert first.error == "RuntimeError: Redis went away"
    failed_logs = [r for r in caplog.records if r.getMessage() == "Trash cleanup failed"]
    assert failed_logs and failed_logs[0].exc_info and failed_logs[0].job.startswith("purge_trash#")

    # one email for the streak, to the owner and admins only
    [(msg, to)] = [s for s in smtp.sent if isinstance(s, tuple) and s[0] != "login"]
    owner = session.exec(select(User).where(User.role == Role.owner)).one()
    assert sorted(to) == sorted([owner.email, "ops@example.com"])
    assert msg["Subject"] == "Dealflow: Trash cleanup failed"
    assert "Redis went away" in msg.get_content() and "/settings?tab=system" in msg.get_content()

    # once it works again, the next failure is news
    jobs.run_job("purge_trash", lambda _: {"deal": 0}, bind=bind)
    with pytest.raises(RuntimeError):
        jobs.run_job("purge_trash", broken, bind=bind)
    assert len([s for s in smtp.sent if isinstance(s, tuple) and s[0] != "login"]) == 2


def test_what_a_run_returned_decides_how_it_went():
    assert jobs.outcome({"deal": 1}) == (JobStatus.succeeded, {"deal": 1}, None)
    assert jobs.outcome({"skipped": "Not due"})[0] == JobStatus.skipped
    status, result, error = jobs.outcome({"reviewed": 3, "problem": "1 of 4 failed"})
    assert (status, result, error) == (JobStatus.warning, {"reviewed": 3}, "1 of 4 failed")


def test_the_morning_review_reports_partial_failures(monkeypatch, session):
    from app.agent.pipeline import ReviewSummary

    monkeypatch.setattr(worker, "get_client", lambda: object())
    monkeypatch.setattr(
        worker,
        "review_stalled_deals",
        lambda s, c: ReviewSummary(reviewed=3, failed=1, proposals=4, stopped_by_budget="Budget"),
    )
    result = worker.pipeline_review_job(session)
    assert result["problem"] == (
        "1 of 4 deal reviews failed; their errors are in the inbox's agent runs; "
        "it stopped early: Budget"
    )
    monkeypatch.setattr(worker, "get_client", lambda: None)
    assert worker.pipeline_review_job(session) == {"skipped": "AI is not configured"}


def test_old_runs_are_pruned(session):
    now = utcnow()
    for days in (1, jobs.JOB_RUN_DAYS + 1):
        session.add(
            JobRun(
                job="purge_trash", status=JobStatus.succeeded, started_at=now - timedelta(days=days)
            )
        )
    session.commit()
    assert jobs.prune(session, now=now) == 1
    assert len(runs(session, "purge_trash")) == 1


# ------------------------------------------------------------------ the status page


def add_run(session, job, status, minutes_ago, error=None):  # noqa: ANN001, ANN201
    started = utcnow() - timedelta(minutes=minutes_ago)
    run = JobRun(
        job=job,
        status=status,
        started_at=started,
        finished_at=None if status == JobStatus.running else started + timedelta(seconds=5),
        error=error,
    )
    session.add(run)
    session.commit()
    return run


def test_status_is_for_admins(client, login, monkeypatch):
    monkeypatch.setattr(settings, "AI_ENABLED", False)
    assert client.get(f"{API}/system/status", headers=login(Role.agent)).status_code == 403
    r = client.get(f"{API}/system/status", headers=login(Role.admin))
    assert r.status_code == 200
    body = r.json()
    assert body["problems"] == []  # nothing has run yet, and this isn't production
    assert [j["job"] for j in body["jobs"]] == [
        "pipeline_review",
        "check_rotting",
        "purge_trash",
        "token_expiry",
    ]
    assert body["jobs"][0]["schedule"] == "Off: the AI agents aren't set up"


def test_status_shows_what_needs_attention(session):
    add_run(session, "check_rotting", JobStatus.succeeded, 5)
    add_run(session, "purge_trash", JobStatus.succeeded, 300)
    add_run(session, "purge_trash", JobStatus.failed, 10, error="RuntimeError: disk full")
    add_run(session, "pipeline_review", JobStatus.warning, 200, error="1 of 4 failed")
    add_run(session, "pipeline_review", JobStatus.skipped, 100)  # doesn't hide the warning
    status = jobs.system_status(session, ai_configured=True)
    assert len(status.problems) == 2
    assert status.problems[0].startswith("Morning pipeline review had a problem on ")
    assert status.problems[0].endswith(": 1 of 4 failed")
    assert status.problems[1].endswith(": RuntimeError: disk full")
    review, rotting, trash, token_expiry = status.jobs
    assert review.last_run.status == JobStatus.skipped and review.last_success_at is None
    assert trash.last_success_at is not None and rotting.schedule == "Every hour"
    assert token_expiry.last_run is None
    assert JobStatus.skipped not in {r.status for r in status.recent_runs}

    # fixed: the next good run clears it
    add_run(session, "purge_trash", JobStatus.succeeded, 1)
    add_run(session, "pipeline_review", JobStatus.succeeded, 1)
    assert jobs.system_status(session, ai_configured=True).problems == []


def test_status_notices_a_stuck_job_and_a_silent_worker(session, monkeypatch):
    add_run(session, "pipeline_review", JobStatus.running, 90)
    add_run(session, "check_rotting", JobStatus.succeeded, 30)  # the worker is alive
    [stuck] = jobs.system_status(session, ai_configured=True).problems
    assert "never finished" in stuck

    for run in session.exec(select(JobRun)).all():
        session.delete(run)
    session.commit()
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    [none_yet] = jobs.system_status(session, ai_configured=True).problems
    assert none_yet.startswith("The background worker hasn't run any jobs yet")
    add_run(session, "check_rotting", JobStatus.succeeded, 60 * 3)
    [silent] = jobs.system_status(session, ai_configured=True).problems
    assert silent.startswith("The background worker hasn't run anything since ")
