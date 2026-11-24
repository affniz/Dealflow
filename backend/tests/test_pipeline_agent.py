"""The pipeline agent, with a scripted stand-in for Claude."""

import json
import re
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlmodel import select

from app.agent import copilot, pipeline
from app.agent.pipeline import review_stalled_deals
from app.main import app
from app.models import AgentProposal, AgentRun, Deal, Role, RunStatus, User, utcnow
from app.services.rotting import check_rotting
from tests.conftest import API
from tests.fakes import FakeClaude, say, tool_call


def _deal(client, h, stage_id, title, value=1000):
    r = client.post(
        f"{API}/deals", headers=h, json={"title": title, "value": value, "stage_id": stage_id}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _stall(session, deal_id, days=20):
    deal = session.get(Deal, deal_id)
    deal.stage_changed_at = utcnow() - timedelta(days=days)
    session.add(deal)
    session.commit()


def reviewer(proposals: int = 1):
    """Plays a sensible review: read the deal, propose follow-ups, write a note."""

    def reply(request: dict[str, Any]) -> dict[str, Any]:
        messages = request["messages"]
        deal_id = int(re.search(r"deal (\d+)", messages[0]["content"]).group(1))
        step = sum(1 for m in messages if m["role"] == "assistant")
        if step == 0:
            return tool_call("get_deal", {"deal_id": deal_id}, f"get_{deal_id}")
        if step <= proposals:
            return tool_call(
                "propose_log_activity",
                {
                    "deal_id": deal_id,
                    "contact_id": None,
                    "type": "task",
                    "subject": f"Follow up #{step}",
                    "body": None,
                    "due_at": "2030-01-02T11:00:00+05:30",
                    "done": False,
                    "reason": "No movement in weeks",
                },
                f"prop_{deal_id}_{step}",
            )
        return say(f"Deal {deal_id} has gone quiet; I proposed a follow-up.")

    return reply


@pytest.fixture
def claude():
    fake = FakeClaude()
    fake.respond = reviewer()
    original = fake.create

    def create(**kwargs):
        fake.script = [fake.respond]
        return original(**kwargs)

    fake.create = create  # type: ignore[method-assign]
    return fake


@pytest.fixture
def team(client, login, session, stages):
    """Two agents with one stalled deal each, plus a fresh deal that shouldn't be reviewed."""
    alice, bob = (
        login(Role.agent, email="alice@example.com"),
        login(Role.agent, email="bob@example.com"),
    )
    a = _deal(client, alice, stages[0], "Alice stalled")
    b = _deal(client, bob, stages[1], "Bob stalled")
    _deal(client, alice, stages[0], "Alice fresh")
    _stall(session, a["id"], 25)  # oldest first
    _stall(session, b["id"], 20)
    check_rotting(session)
    return {"alice": alice, "bob": bob, "a": a, "b": b}


def _proposals(session):
    return session.exec(select(AgentProposal).order_by(AgentProposal.id)).all()


def test_reviews_stalled_deals_as_their_owner(session, claude, team):
    summary = review_stalled_deals(session, claude)
    assert (summary.reviewed, summary.failed, summary.proposals) == (2, 0, 2)

    runs = session.exec(select(AgentRun).order_by(AgentRun.id)).all()
    assert [r.deal_id for r in runs] == [team["a"]["id"], team["b"]["id"]]
    alice = session.exec(select(User).where(User.email == "alice@example.com")).one()
    assert runs[0].user_id == alice.id and runs[0].status == RunStatus.completed
    assert runs[0].summary == f"Deal {team['a']['id']} has gone quiet; I proposed a follow-up."

    props = _proposals(session)
    assert [(p.source, p.user_id, p.run_id) for p in props][0] == (
        "pipeline_agent",
        alice.id,
        runs[0].id,
    )
    assert all(p.status == "pending" for p in props)

    first = claude.requests[0]
    # the static prefix gets its own cache point, shared by every review
    assert first["system"] == [
        {"type": "text", "text": pipeline.SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    assert first["cache_control"] == {"type": "ephemeral"}
    ask, context = first["messages"]
    assert "(“Alice stalled”), 25 days in Lead" in ask["content"]
    assert context["role"] == "system" and "acting for the deal's owner" in context["content"]
    assert "IST" in context["content"]


def test_skips_deals_with_pending_proposals_or_recent_reviews(session, claude, team):
    review_stalled_deals(session, claude)
    assert review_stalled_deals(session, claude).reviewed == 0  # suggestions still pending

    for p in _proposals(session):
        p.status = "rejected"
        session.add(p)
    session.commit()
    assert review_stalled_deals(session, claude).reviewed == 0  # reviewed within the cooldown

    for r in session.exec(select(AgentRun)).all():
        r.created_at = utcnow() - timedelta(days=4)
        session.add(r)
    session.commit()
    assert review_stalled_deals(session, claude).reviewed == 2


def test_at_most_two_proposals_per_deal(session, claude, team):
    claude.respond = reviewer(proposals=3)
    review_stalled_deals(session, claude)
    per_run: dict[int, int] = {}
    for p in _proposals(session):
        per_run[p.run_id] = per_run.get(p.run_id, 0) + 1
    assert set(per_run.values()) == {2}
    third_result = next(
        b
        for req in claude.requests
        for m in req["messages"]
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if b.get("tool_use_id", "").endswith("_3")
    )
    assert third_result["is_error"] is True and "maximum" in third_result["content"]


def test_closing_the_automatic_reminder_doesnt_use_up_the_limit(session, claude, team):
    """Two real changes (say a follow-up and a stage move) and closing Dealflow's generic
    reminder all fit; a third real change still doesn't. The evals caught reviews dropping a
    needed stage move because the reminder used up a slot."""
    two_changes = reviewer(proposals=2)

    def reply(request: dict[str, Any]) -> dict[str, Any]:
        messages = request["messages"]
        step = sum(1 for m in messages if m["role"] == "assistant")
        deal_id = int(re.search(r"deal (\d+)", messages[0]["content"]).group(1))
        if step <= 2:
            return two_changes(request)
        if step == 3:
            reminder = int(re.search(r"not a plan\)?: task #(\d+)", json.dumps(messages)).group(1))
            return tool_call(
                "propose_complete_activity",
                {"activity_id": reminder, "reason": "Covered by the follow-ups"},
                f"done_{deal_id}",
            )
        if step == 4:  # a third real change
            return tool_call(
                "propose_mark_won", {"deal_id": deal_id, "reason": "?"}, f"third_{deal_id}"
            )
        return say("Proposed two follow-ups and closed the reminder.")

    claude.respond = reply
    review_stalled_deals(session, claude)
    a = team["a"]["id"]
    run = session.exec(select(AgentRun).where(AgentRun.deal_id == a)).one()
    results = {
        b["tool_use_id"]: b
        for m in run.messages
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if "tool_use_id" in b
    }
    closed = json.loads(results[f"done_{a}"]["content"])
    assert "is_error" not in results[f"done_{a}"] and closed["counts_toward_limit"] is False
    third = results[f"third_{a}"]
    assert third["is_error"] is True and "maximum" in third["content"]
    actions = [p.action for p in _proposals(session) if p.deal_id == a]
    assert actions == ["log_activity", "log_activity", "complete_activity"]


def test_one_failure_doesnt_stop_the_others(session, claude, team):
    good = reviewer()

    def flaky(request):
        if f"deal {team['a']['id']} " in request["messages"][0]["content"]:
            step = sum(1 for m in request["messages"] if m["role"] == "assistant")
            if step == 1:  # after it already read the deal
                raise RuntimeError("upstream overloaded")
        return good(request)

    claude.respond = flaky
    summary = review_stalled_deals(session, claude)
    assert (summary.reviewed, summary.failed) == (1, 1)
    failed = session.exec(select(AgentRun).where(AgentRun.status == RunStatus.failed)).one()
    assert failed.deal_id == team["a"]["id"] and "overloaded" in failed.error
    # nothing half-done was kept for the failed deal
    assert [p.deal_id for p in _proposals(session)] == [team["b"]["id"]]


def test_run_limit_and_lock(session, claude, team, engine, monkeypatch):
    monkeypatch.setattr(pipeline.settings, "PIPELINE_REVIEW_MAX_DEALS", 1)
    with engine.connect() as other_worker:
        other_worker.execute(text("SELECT pg_advisory_lock(:k)"), {"k": pipeline.LOCK_KEY})
        skipped = review_stalled_deals(session, claude)
        other_worker.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": pipeline.LOCK_KEY})
        other_worker.commit()
    assert skipped.skipped_reason and skipped.reviewed == 0
    assert review_stalled_deals(session, claude).reviewed == 1


def test_inactive_owners_are_skipped(session, claude, team):
    bob = session.exec(select(User).where(User.email == "bob@example.com")).one()
    bob.is_active = False
    session.add(bob)
    session.commit()
    review_stalled_deals(session, claude)
    assert [r.deal_id for r in session.exec(select(AgentRun)).all()] == [team["a"]["id"]]


def test_inbox_endpoints(client, login, session, claude, team, monkeypatch):
    review_stalled_deals(session, claude)
    admin = login(Role.admin)

    # agents see their own reviews and proposals; admins can ask for everyone's
    runs = client.get(f"{API}/agent/runs", headers=team["alice"]).json()
    assert [r["deal"]["name"] for r in runs] == ["Alice stalled"]
    assert runs[0]["proposal_count"] == 1 and runs[0]["summary"].startswith("Deal")
    assert len(client.get(f"{API}/agent/runs", headers=admin).json()) == 2
    mine = client.get(
        f"{API}/proposals", headers=team["alice"], params={"status": "pending"}
    ).json()
    assert [p["deal"]["name"] for p in mine] == ["Alice stalled"] and mine[0]["run_id"]
    assert client.get(f"{API}/proposals", headers=admin).json() == []
    assert len(client.get(f"{API}/proposals", headers=admin, params={"everyone": True}).json()) == 2
    # an agent can't widen their view
    assert (
        len(client.get(f"{API}/proposals", headers=team["alice"], params={"everyone": True}).json())
        == 1
    )

    # approving applies it, marked as the pipeline agent's
    client.post(f"{API}/proposals/{mine[0]['id']}/approve", headers=team["alice"])
    acts = client.get(
        f"{API}/activities", headers=team["alice"], params={"deal_id": team["a"]["id"]}
    ).json()
    assert "pipeline_agent" in [a["via"] for a in acts["data"]]

    # starting a review: admins only, needs AI configured and a reachable worker
    assert client.post(f"{API}/agent/pipeline-review", headers=team["alice"]).status_code == 403
    # no client, even on a machine where the SDK would find an `ant` login
    app.dependency_overrides[copilot.get_client] = lambda: None
    assert client.post(f"{API}/agent/pipeline-review", headers=admin).status_code == 503
    app.dependency_overrides[copilot.get_client] = lambda: claude
    queued = []
    from app import worker

    monkeypatch.setattr(worker.pipeline_review_task, "delay", lambda: queued.append(True))
    r = client.post(f"{API}/agent/pipeline-review", headers=admin)
    assert r.status_code == 202 and queued == [True]


def test_deleting_a_reviewed_deal_keeps_the_run(client, session, claude, team):
    review_stalled_deals(session, claude)
    deal_id = team["a"]["id"]
    assert client.delete(f"{API}/deals/{deal_id}", headers=team["alice"]).status_code == 204
    runs = client.get(f"{API}/agent/runs", headers=team["alice"]).json()
    assert runs and runs[0]["summary"] and runs[0]["deal_id"] is None  # no link while deleted
    r = client.post(f"{API}/trash/deal/{deal_id}/restore", headers=team["alice"])
    assert r.status_code == 200
    runs = client.get(f"{API}/agent/runs", headers=team["alice"]).json()
    assert runs[0]["deal_id"] == deal_id  # the link comes back with the deal


def test_agent_is_told_the_reminder_is_not_a_plan(session, claude, team):
    review_stalled_deals(session, claude)
    deal_result = next(
        b["content"]
        for req in claude.requests
        for m in req["messages"]
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
        if b.get("tool_use_id", "").startswith("get_")
    )
    history = json.loads(deal_result)["history"]
    reminder = [h for h in history if "automatic stalled-deal reminder" in h]
    assert len(reminder) == 1 and "not a plan" in reminder[0]
    assert not any("Follow up, or move it" in h for h in history)  # its generic text is hidden
    assert "never treat it as covering the next step" in pipeline.SYSTEM_PROMPT.replace("\n", " ")
