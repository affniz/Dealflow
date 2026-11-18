"""Per-agent model and effort settings."""

from datetime import timedelta

import pytest

from app.agent import copilot
from app.agent.pipeline import review_stalled_deals
from app.main import app
from app.models import Deal, Role, utcnow
from app.services.rotting import check_rotting
from tests.conftest import API
from tests.fakes import FakeClaude, say, tool_call


@pytest.fixture
def claude(client):
    fake = FakeClaude()
    app.dependency_overrides[copilot.get_client] = lambda: fake
    return fake


def _ask(client, h, text, **extra):
    r = client.post(f"{API}/copilot/messages", headers=h, json={"text": text, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_defaults_and_options(client, login):
    view = client.get(f"{API}/settings/ai", headers=login(Role.agent)).json()
    assert view["settings"] == {
        "copilot_model": "claude-sonnet-5-5",
        "copilot_effort": "medium",
        "pipeline_model": "claude-sonnet-5-5",
        "pipeline_effort": "medium",
    }
    assert [m["id"] for m in view["models"]] == [
        "claude-opus-5-5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    ]
    opus = view["models"][0]
    assert (opus["input_usd_per_mtok"], opus["output_usd_per_mtok"]) == ("4", "20")
    assert view["efforts"] == ["low", "medium", "high", "xhigh", "max"]


def test_only_admins_change_settings_and_only_to_supported_models(client, login):
    admin, agent = login(Role.admin), login(Role.agent)
    body = {"pipeline_model": "claude-haiku-5-5"}
    assert client.patch(f"{API}/settings/ai", headers=agent, json=body).status_code == 403
    r = client.patch(f"{API}/settings/ai", headers=admin, json=body)
    assert r.status_code == 200
    s = r.json()["settings"]
    assert s["pipeline_model"] == "claude-haiku-5-5" and s["copilot_model"] == "claude-sonnet-5-5"
    bad = client.patch(f"{API}/settings/ai", headers=admin, json={"copilot_model": "gpt-9"})
    assert bad.status_code == 422
    effort = client.patch(f"{API}/settings/ai", headers=admin, json={"copilot_effort": "huge"})
    assert effort.status_code == 422


def test_conversations_keep_their_model(client, login, claude):
    admin, agent = login(Role.admin), login(Role.agent)
    claude.script = [say("a"), say("b"), say("c")]
    first = _ask(client, agent, "hi")
    assert first["model"] == "claude-sonnet-5-5"

    client.patch(
        f"{API}/settings/ai",
        headers=admin,
        json={"copilot_model": "claude-opus-5-5", "copilot_effort": "high"},
    )
    _ask(client, agent, "again", conversation_id=first["id"])  # existing chat: unchanged
    second = _ask(client, agent, "new chat")  # new chat: new settings
    assert second["model"] == "claude-opus-5-5"
    models = [(r["model"], r["output_config"]["effort"]) for r in claude.requests]
    assert models == [
        ("claude-sonnet-5-5", "medium"),
        ("claude-sonnet-5-5", "medium"),
        ("claude-opus-5-5", "high"),
    ]


def test_fallback_only_for_models_that_offer_it(client, login, claude):
    admin, agent = login(Role.admin), login(Role.agent)
    claude.script = [say("a"), say("b")]
    _ask(client, agent, "on sonnet")
    client.patch(f"{API}/settings/ai", headers=admin, json={"copilot_model": "claude-haiku-5-5"})
    _ask(client, agent, "on haiku")
    sonnet, haiku = claude.requests
    assert sonnet["fallbacks"] == "default" and sonnet["betas"] == [
        "server-side-fallback-2026-07-01"
    ]
    assert "fallbacks" not in haiku and "betas" not in haiku


def test_pipeline_agent_uses_its_own_settings(client, login, session, stages):
    admin, agent = login(Role.admin), login(Role.agent)
    d = client.post(
        f"{API}/deals", headers=agent, json={"title": "Old", "stage_id": stages[0]}
    ).json()
    deal = session.get(Deal, d["id"])
    deal.stage_changed_at = utcnow() - timedelta(days=30)
    session.add(deal)
    session.commit()
    check_rotting(session)
    client.patch(
        f"{API}/settings/ai",
        headers=admin,
        json={"pipeline_model": "claude-haiku-5-5", "pipeline_effort": "low"},
    )
    fake = FakeClaude()
    fake.script = [tool_call("get_deal", {"deal_id": d["id"]}), say("Quiet deal.")]
    review_stalled_deals(session, fake)
    assert {(r["model"], r["output_config"]["effort"]) for r in fake.requests} == {
        ("claude-haiku-5-5", "low")
    }
