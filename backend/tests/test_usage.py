"""Usage ledger: what each Claude call cost, and the summaries built from it."""

from datetime import timedelta
from decimal import Decimal

import anthropic
import httpx2
import pytest
from anthropic.types.beta import BetaMessage
from sqlmodel import select

from app.agent import copilot
from app.agent.pipeline import review_stalled_deals
from app.agent.pricing import cost_usd
from app.agent.usage import records_from_response
from app.main import app
from app.models import AgentRun, AIUsage, Deal, Role, RunStatus, utcnow
from app.services.rotting import check_rotting
from tests.conftest import API
from tests.fakes import FakeClaude, message, tool_call

USAGE = {
    "input_tokens": 1000,
    "output_tokens": 500,
    "cache_read_input_tokens": 20000,
    "cache_creation_input_tokens": 4000,
    "cache_creation": {"ephemeral_5m_input_tokens": 4000, "ephemeral_1h_input_tokens": 0},
}


@pytest.fixture
def claude(client):
    fake = FakeClaude()
    app.dependency_overrides[copilot.get_client] = lambda: fake
    return fake


def _rows(session):
    return session.exec(select(AIUsage).order_by(AIUsage.id)).all()


def test_pricing():
    # Sonnet 5.5: $2 in, $10 out, $0.10 cache reads, cache writes 1.25x input
    assert cost_usd(
        "claude-sonnet-5-5",
        input_tokens=1000,
        output_tokens=500,
        cache_read_tokens=20000,
        cache_write_5m_tokens=4000,
    ) == Decimal("0.019")
    assert cost_usd("claude-opus-5-5", input_tokens=1_000_000, output_tokens=0) == Decimal("4")
    assert cost_usd(
        "claude-opus-5-5", input_tokens=0, output_tokens=0, cache_write_1h_tokens=1_000_000
    ) == Decimal("8")
    # Haiku 5.5 charges more once a prompt passes 100K tokens
    assert cost_usd("claude-haiku-5-5", input_tokens=50_000, output_tokens=0) == Decimal("0.005")
    assert cost_usd("claude-haiku-5-5", input_tokens=150_000, output_tokens=0) == Decimal("0.075")
    assert cost_usd("claude-unknown-9", input_tokens=10, output_tokens=10) is None


def test_fallback_is_billed_per_model():
    reply = message(
        [{"type": "text", "text": "hi"}],
        usage={
            "input_tokens": 1100,
            "output_tokens": 60,
            "iterations": [
                {
                    "type": "message",
                    "model": "claude-opus-5-5",
                    "input_tokens": 1000,
                    "output_tokens": 10,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
                {
                    "type": "fallback_message",
                    "model": "claude-opus-5",
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 0,
                    "cache_creation_input_tokens": 0,
                },
            ],
        },
        model="claude-opus-5",
    )
    rows = records_from_response(BetaMessage.model_validate(reply), feature="copilot", turn_id="t")
    assert [(r.model, r.input_tokens, r.output_tokens) for r in rows] == [
        ("claude-opus-5-5", 1000, 10),
        ("claude-opus-5", 100, 50),
    ]
    assert rows[0].cost_usd == Decimal("0.0042") and rows[1].cost_usd == Decimal("0.00175")


def test_copilot_turn_is_recorded(client, login, session, claude):
    h = login(Role.agent)
    me = client.get(f"{API}/users/me", headers=h).json()
    claude.script = [
        message(
            [{"type": "tool_use", "id": "t1", "name": "pipeline_overview", "input": {}}],
            "tool_use",
            usage=USAGE,
            model="claude-sonnet-5-5",
        ),
        message([{"type": "text", "text": "Done"}], usage=USAGE, model="claude-sonnet-5-5"),
    ]
    conv = client.post(f"{API}/copilot/messages", headers=h, json={"text": "hi"}).json()

    rows = _rows(session)
    assert len(rows) == 2 and len({r.turn_id for r in rows}) == 1  # one question, two calls
    assert {(r.feature, r.user_id, r.conversation_id, r.model) for r in rows} == {
        ("copilot", me["id"], conv["id"], "claude-sonnet-5-5")
    }
    assert rows[0].cache_read_tokens == 20000 and rows[0].cache_write_tokens == 4000
    assert sum(r.cost_usd for r in rows) == Decimal("0.038")

    mine = client.get(f"{API}/usage/me", headers=h).json()
    assert mine["questions"] == 1 and Decimal(mine["cost_usd"]) == Decimal("0.0380")


def test_failed_turn_still_records_what_was_billed(client, login, session, claude):
    h = login(Role.agent)

    def fail(_):
        raise anthropic.APIConnectionError(
            request=httpx2.Request("POST", "https://api.anthropic.com")
        )

    claude.script = [tool_call("pipeline_overview", {}), fail]
    r = client.post(f"{API}/copilot/messages", headers=h, json={"text": "hi"})
    assert r.status_code == 502
    rows = _rows(session)
    assert len(rows) == 1 and rows[0].feature == "copilot" and rows[0].cost_usd > 0
    # the conversation itself wasn't changed by the failed turn
    convs = client.get(f"{API}/copilot/conversations", headers=h).json()
    view = client.get(f"{API}/copilot/conversations/{convs[0]['id']}", headers=h).json()
    assert view["items"] == []


def test_failed_pipeline_review_still_records_usage(client, login, session, stages):
    h = login(Role.agent)
    d = client.post(f"{API}/deals", headers=h, json={"title": "Old", "stage_id": stages[0]}).json()
    deal = session.get(Deal, d["id"])
    deal.stage_changed_at = utcnow() - timedelta(days=30)
    session.add(deal)
    session.commit()
    check_rotting(session)

    fake = FakeClaude()

    def boom(_):
        raise RuntimeError("overloaded")

    fake.script = [tool_call("get_deal", {"deal_id": d["id"]}), boom]
    review_stalled_deals(session, fake)
    run = session.exec(select(AgentRun)).one()
    rows = _rows(session)
    assert run.status == RunStatus.failed
    assert [(r.feature, r.run_id) for r in rows] == [("pipeline_agent", run.id)]


def test_summary(client, login, session, claude):
    admin, alice = login(Role.admin), login(Role.agent, email="alice@example.com")
    claude.script = [
        message([{"type": "text", "text": "a"}], usage=USAGE, model="claude-sonnet-5-5"),
        message([{"type": "text", "text": "b"}], usage=USAGE, model="claude-opus-5-5"),
        message([{"type": "text", "text": "c"}], usage=USAGE, model="claude-sonnet-5-5"),
    ]
    for text in ("one", "two"):
        client.post(f"{API}/copilot/messages", headers=alice, json={"text": text})
    client.post(f"{API}/copilot/messages", headers=admin, json={"text": "three"})

    s = client.get(f"{API}/usage/summary", headers=admin).json()
    assert s["total"]["calls"] == 3 and s["total"]["units"] == 3
    # each Sonnet call costs $0.019, the Opus one $0.038
    assert Decimal(s["total"]["cost_usd"]) == Decimal("0.0760")
    assert {m["model"]: Decimal(m["cost_usd"]) for m in s["by_model"]} == {
        "claude-opus-5-5": Decimal("0.0380"),
        "claude-sonnet-5-5": Decimal("0.0380"),
    }
    copilot_row = s["by_feature"][0]
    assert copilot_row["feature"] == "copilot" and copilot_row["units"] == 3
    assert Decimal(copilot_row["avg_cost_per_unit"]) == Decimal("0.0253")
    alice_row = next(u for u in s["by_user"] if u["user"]["name"] == "alice@example.com")
    assert alice_row["copilot_questions"] == 2 and Decimal(
        alice_row["copilot_cost_usd"]
    ) == Decimal("0.0570")
    assert len(s["daily"]) == 1 and s["unpriced_calls"] == 0 and s["prices_as_of"]

    # other months are empty; bad months rejected; only admins see the team view
    assert (
        client.get(f"{API}/usage/summary", headers=admin, params={"month": "2020-01"}).json()[
            "total"
        ]["calls"]
        == 0
    )
    assert (
        client.get(f"{API}/usage/summary", headers=admin, params={"month": "2026-13"}).status_code
        == 422
    )
    assert client.get(f"{API}/usage/summary", headers=alice).status_code == 403


def test_get_client_uses_ant_login_or_env(monkeypatch):
    monkeypatch.setattr(copilot.settings, "AI_ENABLED", True)  # CI turns it off
    monkeypatch.setattr(copilot.settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    import anthropic.lib.credentials as creds

    monkeypatch.setattr(creds, "default_credentials", lambda **_: None)
    assert copilot.get_client() is None
    monkeypatch.setattr(creds, "default_credentials", lambda **_: object())  # an `ant` profile
    assert copilot.get_client() is not None
    monkeypatch.setattr(creds, "default_credentials", lambda **_: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    assert copilot.get_client() is not None
    monkeypatch.setattr(copilot.settings, "AI_ENABLED", False)  # off wins over credentials
    assert copilot.get_client() is None
