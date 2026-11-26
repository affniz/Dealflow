"""The scripted stand-in for Claude that the end-to-end tests run the Copilot with."""

import pytest

from app.agent import copilot
from app.agent.scripted import ScriptedClaude
from app.core.config import Settings
from app.main import app
from app.models import Role
from tests.conftest import API


def test_on_only_when_asked_and_never_in_production(monkeypatch):
    monkeypatch.setattr(copilot.settings, "AI_ENABLED", True)
    monkeypatch.setattr(copilot.settings, "AI_SCRIPTED", True)
    assert isinstance(copilot.get_client(), ScriptedClaude)
    monkeypatch.setattr(copilot.settings, "AI_ENABLED", False)
    assert copilot.get_client() is None

    prod = {
        "ENVIRONMENT": "production",
        "SECRET_KEY": "a-real-secret-for-this-test",
        "FIRST_OWNER_PASSWORD": "a-real-password",
    }
    Settings(**prod)  # fine without it
    with pytest.raises(ValueError, match="AI_SCRIPTED is for tests"):
        Settings(**prod, AI_SCRIPTED=True)


@pytest.fixture
def scripted(client):
    app.dependency_overrides[copilot.get_client] = ScriptedClaude
    yield


def _chat(client, h, text):
    r = client.post(f"{API}/copilot/messages", headers=h, json={"text": text})
    assert r.status_code == 202, r.text
    view = client.get(f"{API}/copilot/conversations/{r.json()['id']}", headers=h).json()
    assert not view["running"]
    return view


def _deal(client, h, title, stage_id):
    r = client.post(f"{API}/deals", headers=h, json={"title": title, "stage_id": stage_id})
    assert r.status_code == 201, r.text
    return r.json()


def test_moves_a_deal_through_the_real_tools(client, login, scripted, stages):
    h = login(Role.agent)
    deal = _deal(client, h, "Fleet rollout", stages[0])
    view = _chat(client, h, "Move Fleet rollout to Proposal")

    steps = [i["text"] for i in view["items"] if i["kind"] == "step"]
    assert steps == [
        "Searched deals for “Fleet rollout”",
        "Checked the pipeline",
        "Proposed a change",
    ]
    assert view["items"][-1]["text"].startswith("I've suggested moving **Fleet rollout**")
    [proposal] = view["proposals"]
    assert proposal["summary"] == "Move “Fleet rollout” from Lead to Proposal"
    assert proposal["deal"]["id"] == deal["id"]

    # a second move in the same chat gets its own card
    _deal(client, h, "Clinic suite", stages[0])
    view = _chat_more(client, h, view["id"], "move clinic suite to negotiation.")
    assert len({p["id"] for p in view["proposals"]}) == 2
    cards = [i["proposal_id"] for i in view["items"] if i.get("proposal_id")]
    assert cards == [p["id"] for p in view["proposals"]]


def _chat_more(client, h, conversation_id, text):
    body = {"text": text, "conversation_id": conversation_id}
    r = client.post(f"{API}/copilot/messages", headers=h, json=body)
    assert r.status_code == 202, r.text
    return client.get(f"{API}/copilot/conversations/{conversation_id}", headers=h).json()


def test_answers_from_what_the_user_can_see(client, login, scripted, stages):
    alice, bob = login(Role.agent), login(Role.agent)
    _deal(client, bob, "Bob's deal", stages[0])
    view = _chat(client, alice, "Move Bob's deal to Proposal")
    assert view["items"][-1]["text"] == (
        "I couldn't find an open deal called “Bob's deal” that you can see."
    )
    assert view["proposals"] == []

    view = _chat(client, alice, "Which deals are stalled?")
    assert view["items"][-1]["text"] == "None of the open deals you can see are stalled."


def test_viewers_get_the_tools_refusal(client, login, scripted, stages):
    _deal(client, login(Role.admin), "Licence", stages[0])
    view = _chat(client, login(Role.viewer), "Move Licence to Proposal")
    assert view["items"][-1]["text"].startswith("I couldn't suggest that: This user is a viewer")
    assert view["proposals"] == []


def test_fail_means_claude_cant_be_reached(client, login, scripted):
    view = _chat(client, login(Role.agent), "Please fail")
    assert view["failure"]["message"] == "Copilot couldn't reach Claude just now. Try again."
