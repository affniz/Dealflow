"""Monthly AI budgets: per-person Copilot limits and a team limit for the pipeline agent."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlmodel import select

from app.agent import copilot
from app.agent.pipeline import review_stalled_deals
from app.main import app
from app.models import AgentConversation, AIUsage, Deal, Role, utcnow
from app.services.rotting import check_rotting
from tests.conftest import API
from tests.fakes import FakeClaude, message, say

# one Sonnet call with this usage costs $0.019
USAGE = {
    "input_tokens": 1000,
    "output_tokens": 500,
    "cache_read_input_tokens": 20000,
    "cache_creation_input_tokens": 4000,
    "cache_creation": {"ephemeral_5m_input_tokens": 4000, "ephemeral_1h_input_tokens": 0},
}


def costly(content, stop="end_turn"):
    return message(content, stop, usage=USAGE, model="claude-sonnet-5-5")


@pytest.fixture
def claude(client):
    fake = FakeClaude()
    app.dependency_overrides[copilot.get_client] = lambda: fake
    return fake


def _set(client, admin, copilot_limit, pipeline_limit):
    body = {"copilot_per_person_usd": copilot_limit, "pipeline_team_usd": pipeline_limit}
    r = client.put(f"{API}/settings/budgets", headers=admin, json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_defaults_and_admin_changes(client, login):
    admin, agent = login(Role.admin), login(Role.agent)
    assert client.get(f"{API}/settings/budgets", headers=admin).json() == {
        "copilot_per_person_usd": "10",
        "pipeline_team_usd": "20",
    }
    assert client.get(f"{API}/settings/budgets", headers=agent).status_code == 403
    body = {"copilot_per_person_usd": "5", "pipeline_team_usd": None}
    assert client.put(f"{API}/settings/budgets", headers=agent, json=body).status_code == 403
    assert _set(client, admin, "5.50", None) == {
        "copilot_per_person_usd": "5.50",
        "pipeline_team_usd": None,
    }
    for bad in ("-1", "1.234"):
        r = client.put(
            f"{API}/settings/budgets",
            headers=admin,
            json={"copilot_per_person_usd": bad, "pipeline_team_usd": None},
        )
        assert r.status_code == 422


def test_copilot_refuses_once_the_budget_is_used(client, login, claude, session):
    admin, alice, bob = login(Role.admin), login(Role.agent), login(Role.agent)
    _set(client, admin, "0.01", "20")
    claude.script = [costly([{"type": "text", "text": "Sure."}])]
    first = client.post(f"{API}/copilot/messages", headers=alice, json={"text": "hi"})
    assert first.status_code == 200  # $0 spent before this call

    calls, conversations = len(claude.requests), session.exec(select(AgentConversation)).all()
    r = client.post(f"{API}/copilot/messages", headers=alice, json={"text": "again"})
    assert r.status_code == 429
    assert "Copilot budget" in r.json()["detail"] and "resets on" in r.json()["detail"]
    # refused before calling the model or creating a chat
    assert len(claude.requests) == calls
    assert len(session.exec(select(AgentConversation)).all()) == len(conversations)

    # limits are per person: Bob can still ask
    claude.script = [say("Hi Bob")]
    assert (
        client.post(f"{API}/copilot/messages", headers=bob, json={"text": "hi"}).status_code == 200
    )

    me = client.get(f"{API}/usage/me", headers=alice).json()
    assert me["budget_usd"] == "0.01" and me["budget_used_pct"] == 190 and me["resets_on"]


def test_copilot_stops_mid_answer_when_the_budget_runs_out(client, login, claude):
    admin, h = login(Role.admin), login(Role.agent)
    _set(client, admin, "0.01", "20")  # the first call ($0.019) uses it up
    claude.script = [
        costly(
            [{"type": "tool_use", "id": "t1", "name": "pipeline_overview", "input": {}}], "tool_use"
        )
    ]
    r = client.post(f"{API}/copilot/messages", headers=h, json={"text": "overview?"})
    assert r.status_code == 200
    assert len(claude.requests) == 1  # never made the second call
    last = r.json()["items"][-1]
    assert last["kind"] == "assistant" and last["text"].startswith("I've had to stop here:")

    # the stored history is still valid: every tool_use has its result
    convs = client.get(f"{API}/copilot/conversations", headers=h).json()
    _set(client, admin, None, "20")
    claude.script = [say("ok")]
    client.post(
        f"{API}/copilot/messages",
        headers=h,
        json={"text": "go on", "conversation_id": convs[0]["id"]},
    )
    msgs = claude.requests[-1]["messages"]
    uses = [
        b["id"]
        for m in msgs
        if m["role"] == "assistant" and isinstance(m["content"], list)
        for b in m["content"]
        if b["type"] == "tool_use"
    ]
    results = [
        b["tool_use_id"]
        for m in msgs
        if m["role"] == "user" and isinstance(m["content"], list)
        for b in m["content"]
    ]
    assert uses == results == ["t1"]


def test_no_limit_means_no_limit(client, login, claude):
    admin, h = login(Role.admin), login(Role.agent)
    _set(client, admin, None, None)
    claude.script = [costly([{"type": "text", "text": "a"}]) for _ in range(3)]
    for text in ("a", "b", "c"):
        assert (
            client.post(f"{API}/copilot/messages", headers=h, json={"text": text}).status_code
            == 200
        )
    me = client.get(f"{API}/usage/me", headers=h).json()
    assert me["budget_usd"] is None and me["budget_used_pct"] is None


def _stalled(client, h, session, stage_id, title):
    d = client.post(f"{API}/deals", headers=h, json={"title": title, "stage_id": stage_id}).json()
    deal = session.get(Deal, d["id"])
    deal.stage_changed_at = utcnow() - timedelta(days=30)
    session.add(deal)
    session.commit()
    return d


def test_pipeline_agent_stops_at_the_team_budget(client, login, session, stages):
    admin, h = login(Role.admin), login(Role.agent)
    a = _stalled(client, h, session, stages[0], "First")
    b = _stalled(client, h, session, stages[0], "Second")
    check_rotting(session)

    _set(client, admin, "10", "0")  # nothing allowed
    fake = FakeClaude()
    s = review_stalled_deals(session, fake)
    assert s.reviewed == 0 and "budget" in s.stopped_by_budget and fake.requests == []

    _set(client, admin, "10", "0.01")  # enough for one deal's first call, not the second deal
    fake.script = [
        costly(
            [{"type": "tool_use", "id": "g1", "name": "get_deal", "input": {"deal_id": a["id"]}}],
            "tool_use",
        ),
    ]
    s = review_stalled_deals(session, fake)
    assert s.reviewed == 1 and s.stopped_by_budget and len(fake.requests) == 1
    spent = sum(r.cost_usd for r in session.exec(select(AIUsage)).all())
    assert spent == Decimal("0.019")  # overshot by at most one call
    assert b["id"] not in [
        r["deal_id"] for r in client.get(f"{API}/agent/runs", headers=admin).json()
    ]

    summary = client.get(f"{API}/usage/summary", headers=admin).json()
    assert summary["pipeline_budget"] == {
        "budget_usd": "0.01",
        "spent_usd": "0.0190",
        "used_pct": 190,
    }
    assert summary["copilot_budget_per_person_usd"] == "10"
    past = client.get(f"{API}/usage/summary", headers=admin, params={"month": "2020-01"}).json()
    assert past["pipeline_budget"] is None
