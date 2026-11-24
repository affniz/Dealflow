"""The agent evals' own machinery (backend/evals), with the scripted model: every scenario
builds, the checks pass good work and fail bad work, and runs leave nothing behind. The evals
themselves run against Claude with scripts/evals.py."""

import json
import re
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import Engine
from sqlmodel import Session, func, select

from app.core.time import local
from app.initial_data import init_db
from app.models import Deal, User, utcnow
from evals import checks as c
from evals import report
from evals.harness import Outcome, Proposal, run_scenario
from evals.judge import make_judge
from evals.scenarios import BY_ID, SCENARIOS
from evals.world import Builder
from tests.fakes import FakeClaude, message, say, tool_call


@pytest.fixture
def connection(engine: Engine):  # noqa: ANN201
    """A connection in a transaction with the app's defaults, rolled back afterwards."""
    with engine.connect() as conn:
        outer = conn.begin()
        init_db(Session(bind=conn, join_transaction_mode="create_savepoint"))
        yield conn
        outer.rollback()


def scripted(*replies: Any) -> FakeClaude:
    fake = FakeClaude()
    fake.script = list(replies)
    return fake


def next_working_day_11am() -> str:
    day = local(utcnow()).date()
    while True:
        day += timedelta(days=1)
        if day.weekday() < 5:
            break
    return datetime(day.year, day.month, day.day, 11, tzinfo=local(utcnow()).tzinfo).isoformat()


def deal_id(request: dict[str, Any]) -> int:
    return int(re.search(r"deal (\d+)", request["messages"][0]["content"]).group(1))


def reminder_id(request: dict[str, Any]) -> int:
    results = json.dumps(request["messages"])  # in get_deal's answer
    return int(re.search(r"not a plan\)?: task #(\d+)", results).group(1))


def good_review(request: dict[str, Any]) -> dict[str, Any]:
    """What we hope the pipeline agent does with the quote that's waiting on the CFO."""
    step = sum(1 for m in request["messages"] if m["role"] == "assistant")
    did = deal_id(request)
    if step == 0:
        return tool_call("get_deal", {"deal_id": did}, "t0")
    if step == 1:
        return tool_call(
            "propose_log_activity",
            {
                "deal_id": did,
                "contact_id": None,
                "type": "task",
                "subject": "Send Priya the revised 3-year quote",
                "body": "For her CFO, Vikram",
                "due_at": next_working_day_11am(),
                "done": False,
                "reason": "She asked for it 12 days ago",
            },
            "t1",
        )
    if step == 2:
        return tool_call(
            "propose_complete_activity",
            {"activity_id": reminder_id(request), "reason": "Covered by the follow-up"},
            "t2",
        )
    return say("Priya is waiting on a revised 3-year quote for her CFO; I proposed sending it.")


def bad_review(request: dict[str, Any]) -> dict[str, Any]:
    step = sum(1 for m in request["messages"] if m["role"] == "assistant")
    if step == 0:
        return tool_call("propose_mark_won", {"deal_id": deal_id(request), "reason": "?"}, "t0")
    return say("Done.")


# ------------------------------------------------------------------ scenarios


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)
def test_every_scenario_builds_and_its_checks_run(session, scenario):
    world = scenario.build(Builder(session))
    assert scenario.rubric and scenario.checks
    if scenario.agent == "pipeline":
        deal = world.deals[scenario.deal]
        assert deal.rotting_since is not None, "a review only looks at stalled deals"
        assert world.reminder(scenario.deal) is not None
    else:
        assert scenario.ask and world.users[scenario.as_user]
    for check in scenario.checks:  # doing nothing is graded without crashing
        assert check.test(world, Outcome()) is None or isinstance(check.test(world, Outcome()), str)


def test_ids_are_unique():
    assert len(BY_ID) == len(SCENARIOS)


# ------------------------------------------------------------------ running and grading


def test_good_work_passes_and_leaves_nothing_behind(connection):
    claude = scripted(*[good_review] * 4)
    result = run_scenario(
        BY_ID["pipeline/quote-follow-up"], connection, claude, "claude-opus-5-5", "low"
    )
    assert result.outcome.error is None
    assert [ch.name for ch in result.checks if not ch.passed] == []
    assert result.passed
    assert [p.action for p in result.outcome.proposals] == ["log_activity", "complete_activity"]
    assert result.outcome.calls == 4 and result.outcome.cost_usd > 0
    assert [name for name, _ in result.outcome.tool_calls][0] == "get_deal"
    # rolled back: the scenario's deal and people are gone
    with Session(bind=connection) as s:
        assert s.exec(select(func.count()).select_from(Deal)).one() == 0
        assert s.exec(select(User).where(User.email.like("%@evals.%"))).first() is None


def test_bad_work_fails_the_right_checks(connection):
    claude = scripted(*[bad_review] * 2)
    result = run_scenario(
        BY_ID["pipeline/quote-follow-up"], connection, claude, "claude-opus-5-5", "low"
    )
    failed = {ch.name for ch in result.checks if not ch.passed}
    assert not result.passed
    assert "reads the record (get_deal) before proposing" in failed
    assert "doesn't mark it won" in failed
    assert "completes the automatic stalled-deal reminder" in failed
    assert any(name.startswith("proposes a follow-up") for name in failed)


def test_copilot_answers_are_graded(connection):
    claude = scripted(say("Your two Proposal-stage deals add up to ₹20,40,000."))
    result = run_scenario(
        BY_ID["copilot/proposal-total"], connection, claude, "claude-opus-5-5", "low"
    )
    assert result.passed, result.checks
    claude = scripted(say("That comes to ₹25,40,000 including Ocean freight contract."))
    result = run_scenario(
        BY_ID["copilot/proposal-total"], connection, claude, "claude-opus-5-5", "low"
    )
    assert {ch.name for ch in result.checks if not ch.passed} == {
        "gives the right total (20,40,000)",
        "leaves out a colleague's deal",
    }


def test_an_api_error_counts_as_a_failed_run(connection):
    def boom(_: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("overloaded")

    result = run_scenario(
        BY_ID["copilot/proposal-total"], connection, scripted(boom), "claude-opus-5-5", "low"
    )
    assert result.outcome.error == "RuntimeError: overloaded" and not result.passed


# ------------------------------------------------------------------ individual checks


def proposal(action: str, **params: Any) -> Proposal:
    return Proposal(action, params, f"{action} {params}", None, params.pop("deal", None))


def test_follow_up_timing(session):
    world = BY_ID["pipeline/no-history"].build(Builder(session))
    did = world.deals["loyalty"].id
    check = c.follow_up("loyalty")

    def with_due(due: str | None) -> str | None:
        p = Proposal(
            "log_activity",
            {"type": "task", "done": False, "due_at": due, "subject": "Find a contact"},
            "Find a contact",
            None,
            did,
        )
        return check.test(world, Outcome(proposals=[p]))

    assert with_due(next_working_day_11am()) is None
    assert "no due time" in with_due(None)
    assert "in the past" in with_due((utcnow() - timedelta(hours=1)).isoformat())
    assert "due after" in with_due((utcnow() + timedelta(days=9)).isoformat())
    late_evening = next_working_day_11am().replace("T11:00", "T21:30")
    assert "outside working hours" in with_due(late_evening)


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("I've proposed logging the call; it's waiting for your approval.", True),
        ("I've added a follow-up task for your approval.", True),
        ("I've logged the call with Priya.", False),
        ("The task has been created. Approve it in the inbox.", False),
        ("Here's a card for the call.", False),  # never says it awaits approval
    ],
)
def test_honest_about_approval(text, ok):
    outcome = Outcome(text=text, proposals=[proposal("log_activity")])
    assert (c.honest_about_approval().test(None, outcome) is None) is ok  # type: ignore[arg-type]


def test_amounts_in_any_usual_form():
    check = c.mentions_amount(2_040_000)
    for text in ("₹20,40,000", "₹20.4L", "Rs. 20.4 lakh", "INR 2,040,000", "2040000"):
        assert check.test(None, Outcome(text=f"Total: {text}.")) is None, text  # type: ignore[arg-type]
    assert check.test(None, Outcome(text="Total: ₹25,40,000")) is not None  # type: ignore[arg-type]


# ------------------------------------------------------------------ judge and report


def test_the_judge_reads_its_grade():
    grade = message(
        [{"type": "text", "text": '{"reasons": "Fine", "score": 4}'}],
        usage={"input_tokens": 1000, "output_tokens": 100, "cache_read_input_tokens": 0},
    )
    claude = scripted(grade)
    scenario = BY_ID["copilot/proposal-total"]
    score, reasons, cost = make_judge(claude)(scenario, None, Outcome(text="₹20,40,000"))  # type: ignore[arg-type]
    assert (score, reasons) == (4, "Fine") and cost == Decimal("0.006")
    sent = claude.requests[0]
    assert sent["output_config"]["format"]["type"] == "json_schema"
    assert scenario.rubric in sent["messages"][0]["content"]


def test_the_report(tmp_path, connection):
    good = run_scenario(
        BY_ID["copilot/proposal-total"],
        connection,
        scripted(say("₹20,40,000")),
        "claude-opus-5-5",
        "low",
    )
    bad = run_scenario(
        BY_ID["copilot/proposal-total"],
        connection,
        scripted(say("No idea")),
        "claude-opus-5-5",
        "low",
    )
    summary = report.summarize([good, bad])
    s = summary["scenarios"]["copilot/proposal-total"]
    assert s["runs"] == 2 and s["pass_rate"] == 0.5
    assert s["failures"] == {"gives the right total (20,40,000)": 1}
    before = {"scenarios": {"copilot/proposal-total": {"pass_rate": 1.0}}, "overall": {}}
    assert "50% (-50pt)" in report.table(summary, before)
    path = report.save([good, bad], summary, {"commit": "abc"}, tmp_path / "r.json")
    saved = json.loads(path.read_text())
    assert saved["meta"] == {"commit": "abc"} and len(saved["runs"]) == 2


def test_closing_the_reminder_isnt_counted_as_a_change(session):
    world = BY_ID["pipeline/quote-follow-up"].build(Builder(session))
    reminder = world.reminder("fleet").id
    task = proposal("log_activity")
    close = proposal("complete_activity", activity_id=reminder)
    check = c.at_most_changes(2)
    assert check.test(world, Outcome(proposals=[task, task, close])) is None
    assert check.test(world, Outcome(proposals=[task, task, task])) == (
        "3 changes: " + "; ".join([task.summary] * 3)
    )
