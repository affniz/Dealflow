"""Copilot tests with a scripted stand-in for Claude: no network, no API key, no cost."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import anthropic
import httpx2
import pytest
from sqlmodel import select

from app.agent import copilot, turns
from app.agent.tools import TOOL_SPECS
from app.api.routes import copilot as copilot_routes
from app.main import app
from app.models import (
    AgentConversation,
    AgentProposal,
    AIUsage,
    ConversationView,
    Deal,
    Role,
    utcnow,
)
from app.services.rotting import check_rotting
from tests.conftest import API
from tests.fakes import FakeClaude, message, say, tool_call


@pytest.fixture
def claude(client):
    fake = FakeClaude()
    app.dependency_overrides[copilot.get_client] = lambda: fake
    yield fake


def _deal(client, h, stage_id, title="Deal", value=1000):
    body = {"title": title, "value": value, "stage_id": stage_id}
    r = client.post(f"{API}/deals", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _ask(client, h, text, **extra):
    return client.post(f"{API}/copilot/messages", headers=h, json={"text": text, **extra})


def test_not_configured_without_api_key(client, login, monkeypatch):
    # a developer's own `ant` login or env key must not leak into this test
    monkeypatch.setattr(copilot.settings, "ANTHROPIC_API_KEY", None)
    monkeypatch.setattr(copilot, "_sdk_has_credentials", lambda: False)
    h = login(Role.agent)
    assert client.get(f"{API}/copilot/status", headers=h).json() == {
        "enabled": False,
        "review_hour": 7,
        "timezone": "Asia/Kolkata",
        "pipeline_budget_reached": None,
    }
    r = _ask(client, h, "hello")
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_tool_specs_are_strict():
    for spec in TOOL_SPECS:
        schema = spec["input_schema"]
        assert spec["strict"] is True
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])


def test_read_tool_loop_and_request_shape(client, login, claude, session, stages):
    h = login(Role.agent)
    stale = _deal(client, h, stages[0], title="Supplier portal")
    _deal(client, h, stages[0], title="Fresh deal")
    deal = session.get(Deal, stale["id"])
    deal.stage_changed_at = utcnow() - timedelta(days=20)
    session.add(deal)
    session.commit()
    check_rotting(session)

    query = {"query": None, "status": "open", "stalled_only": True, "mine_only": True, "limit": 10}
    claude.script = [
        tool_call("search_deals", query),
        say("One deal is stalled: Supplier portal (20 days in Lead)."),
    ]
    r = _ask(client, h, "What's stalled?", deal_id=stale["id"])
    assert r.status_code == 202, r.text
    view = r.json()
    assert [(i["kind"], i["text"]) for i in view["items"]] == [
        ("user", "What's stalled?"),
        ("step", "Searched deals"),
        ("assistant", "One deal is stalled: Supplier portal (20 days in Lead)."),
    ]

    first, second = claude.requests
    assert first["model"] == "claude-sonnet-5-5"  # the default for the Copilot
    assert first["output_config"] == {"effort": "medium"}
    assert first["tools"] == TOOL_SPECS and first["fallbacks"] == "default"
    user_msg, context = first["messages"][-2:]
    assert user_msg == {"role": "user", "content": "What's stalled?"}
    assert context["role"] == "system" and "Supplier portal" in context["content"]
    # the tool ran with the agent's access and found only the stalled deal
    result = json.loads(claude.tool_results(1)[0]["content"])
    assert [d["title"] for d in result["deals"]] == ["Supplier portal"]
    # append-only: the second request starts with the first one's messages, thinking included
    assert second["messages"][: len(first["messages"])] == first["messages"]
    assert second["messages"][len(first["messages"])]["content"][0]["signature"] == "sig"


def test_follow_up_turn_appends_to_history(client, login, claude):
    h = login(Role.agent)
    claude.script = [say("Hi!"), say("Still here.")]
    conv = _ask(client, h, "Hello").json()
    second = _ask(client, h, "Are you there?", conversation_id=conv["id"]).json()
    assert [i["text"] for i in second["items"]] == ["Hello", "Hi!", "Are you there?", "Still here."]
    a, b = claude.requests
    assert b["messages"][: len(a["messages"]) + 1][:-1] == a["messages"]
    # someone else can't read or continue it
    other = login(Role.agent)
    assert client.get(f"{API}/copilot/conversations/{conv['id']}", headers=other).status_code == 404
    claude.script = [say("x")]
    assert _ask(client, other, "hi", conversation_id=conv["id"]).status_code == 404
    listed = client.get(f"{API}/copilot/conversations", headers=h).json()
    assert [c["title"] for c in listed] == ["Hello"]


def test_proposal_needs_approval_then_applies_via_copilot(client, login, claude, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0], title="Annual licence")
    claude.script = [
        tool_call(
            "propose_move_stage",
            {"deal_id": d["id"], "stage_id": stages[2], "reason": "Proposal was sent today"},
        ),
        say("I've proposed moving it to Proposal; approve it when you're ready."),
    ]
    view = _ask(client, h, "Move Annual licence to Proposal").json()
    step = next(i for i in view["items"] if i["kind"] == "step")
    proposal = view["proposals"][0]
    assert step["proposal_id"] == proposal["id"] and proposal["status"] == "pending"
    assert proposal["summary"] == "Move “Annual licence” from Lead to Proposal"
    assert proposal["deal"]["name"] == "Annual licence"
    # nothing changed yet
    assert client.get(f"{API}/deals/{d['id']}", headers=h).json()["stage_id"] == stages[0]

    pending = client.get(f"{API}/proposals", headers=h, params={"status": "pending"}).json()
    assert [p["id"] for p in pending] == [proposal["id"]]
    r = client.post(f"{API}/proposals/{proposal['id']}/approve", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    assert client.get(f"{API}/deals/{d['id']}", headers=h).json()["stage_id"] == stages[2]
    timeline = client.get(f"{API}/deals/{d['id']}/timeline", headers=h).json()
    moved = next(
        i["event"]
        for i in timeline
        if i["kind"] == "event" and i["event"]["kind"] == "stage_changed"
    )
    assert moved["data"]["via"] == "copilot"
    assert client.post(f"{API}/proposals/{proposal['id']}/approve", headers=h).status_code == 409


def test_rejected_and_failed_proposals(client, login, claude, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0], title="Pilot")
    claude.script = [
        tool_call("propose_mark_won", {"deal_id": d["id"], "reason": "Signed"}, "toolu_a"),
        say("Proposed."),
        tool_call(
            "propose_log_activity",
            {
                "deal_id": d["id"],
                "contact_id": None,
                "type": "task",
                "subject": "Send invoice",
                "body": None,
                "due_at": "2030-01-01T09:00:00+05:30",
                "done": False,
                "reason": "Billing",
            },
            "toolu_b",
        ),
        say("Proposed a task."),
    ]
    won = _ask(client, h, "We won Pilot").json()["proposals"][0]
    task = _ask(client, h, "Add an invoice task").json()["proposals"][0]

    # the deal gets closed by hand before the proposal is approved
    lost_reason = client.get(f"{API}/lost-reasons", headers=h).json()[0]["id"]
    client.post(f"{API}/deals/{d['id']}/lost", headers=h, json={"lost_reason_id": lost_reason})
    r = client.post(f"{API}/proposals/{won['id']}/approve", headers=h).json()
    assert r["status"] == "failed" and "already lost" in r["error"]

    r = client.post(f"{API}/proposals/{task['id']}/reject", headers=h).json()
    assert r["status"] == "rejected"
    acts = client.get(f"{API}/activities", headers=h, params={"deal_id": d["id"]}).json()
    assert acts["count"] == 0


def test_approved_task_is_marked_as_added_by_copilot(client, login, claude, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0])
    inp = {
        "deal_id": d["id"],
        "contact_id": None,
        "type": "task",
        "subject": "Call back",
        "body": "Ask about budget",
        "due_at": "2030-01-01T09:00:00Z",
        "done": False,
        "reason": "Follow up",
    }
    claude.script = [tool_call("propose_log_activity", inp), say("Done.")]
    p = _ask(client, h, "remind me").json()["proposals"][0]
    # shown in the team's time zone (IST by default)
    assert p["summary"] == "Add task on “Deal”: Call back, due 01 Jan, 14:30 IST"
    client.post(f"{API}/proposals/{p['id']}/approve", headers=h)
    act = client.get(f"{API}/activities", headers=h, params={"deal_id": d["id"]}).json()["data"][0]
    assert act["via"] == "copilot" and act["due_at"] == "2030-01-01T09:00:00Z"


def test_agent_copilot_cant_see_teammates_deals(client, login, claude, stages):
    alice, bob = login(Role.agent), login(Role.agent)
    secret = _deal(client, alice, stages[0], title="Alice's secret deal")
    claude.script = [
        tool_call("get_deal", {"deal_id": secret["id"]}),
        tool_call("propose_mark_won", {"deal_id": secret["id"], "reason": "x"}, "toolu_2"),
        say("I can't find that deal."),
    ]
    view = _ask(client, bob, "Tell me about deal").json()
    for i in (1, 2):
        result = claude.tool_results(i)[0]
        assert result["is_error"] is True and "isn't visible" in result["content"]
        assert "secret" not in result["content"]
    assert view["proposals"] == []


def test_viewer_cant_propose(client, login, claude, stages):
    d = _deal(client, login(Role.agent), stages[0])
    viewer = login(Role.viewer)
    claude.script = [
        tool_call("propose_mark_won", {"deal_id": d["id"], "reason": "x"}),
        say("You're a viewer, so I can't change it."),
    ]
    view = _ask(client, viewer, "mark it won").json()
    assert view["proposals"] == []
    assert "viewer" in claude.tool_results(1)[0]["content"]


def test_invalid_tool_input_is_reported_back(client, login, claude):
    h = login(Role.agent)
    claude.script = [tool_call("get_deal", {"deal_id": "not a number"}), say("Sorry.")]
    _ask(client, h, "?")
    result = claude.tool_results(1)[0]
    assert result["is_error"] is True and result["content"].startswith("Invalid input")


def test_step_limit_keeps_history_valid(client, login, claude, monkeypatch):
    monkeypatch.setattr(copilot.settings, "COPILOT_MAX_STEPS", 3)
    h = login(Role.agent)
    overview = tool_call("pipeline_overview", {})
    claude.script = [overview, overview, overview]
    view = _ask(client, h, "loop forever").json()
    assert len(claude.requests) == 3
    assert view["items"][-1]["text"].startswith("I've run out of steps")
    # every tool_use in the stored history has a matching tool_result
    claude.script = [say("ok")]
    _ask(client, h, "continue", conversation_id=view["id"])
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
    assert uses == results


def test_due_time_without_zone_means_team_time(client, login, claude, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0])
    inp = {
        "deal_id": d["id"],
        "contact_id": None,
        "type": "task",
        "subject": "Demo",
        "body": None,
        "due_at": "2030-01-01T10:00:00",
        "done": False,
        "reason": "x",
    }
    claude.script = [tool_call("propose_log_activity", inp), say(".")]
    p = _ask(client, h, "book it").json()["proposals"][0]
    assert p["summary"].endswith("due 01 Jan, 10:00 IST")
    client.post(f"{API}/proposals/{p['id']}/approve", headers=h)
    act = client.get(f"{API}/activities", headers=h, params={"deal_id": d["id"]}).json()["data"][0]
    assert act["due_at"] == "2030-01-01T04:30:00Z"
    context = claude.requests[0]["messages"][-1]["content"]
    assert "IST (UTC+0530)" in context


def test_refusal_ends_the_turn_politely(client, login, claude):
    h = login(Role.agent)
    claude.script = [message([], "refusal")]
    view = _ask(client, h, "something odd").json()
    assert view["items"][-1]["text"] == "Sorry, I can't help with that one."


def test_deleting_a_deal_fails_its_pending_proposals(client, login, claude, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0])
    claude.script = [tool_call("propose_mark_won", {"deal_id": d["id"], "reason": "x"}), say(".")]
    p = _ask(client, h, "won").json()["proposals"][0]
    assert client.delete(f"{API}/deals/{d['id']}", headers=h).status_code == 204
    after = client.get(f"{API}/proposals", headers=h).json()[0]
    assert after["id"] == p["id"] and after["status"] == "failed" and after["deal_id"] is None


def test_prompt_versions_stay_fixed_per_conversation(client, login, claude, session, monkeypatch):
    from app.models import AgentConversation

    h = login(Role.agent)
    me = client.get(f"{API}/users/me", headers=h).json()
    claude.script = [say("new"), say("old"), say("still new")]

    # a new chat starts on the current prompt, sent with its own cache point
    new = _ask(client, h, "hello").json()
    sent = claude.requests[0]["system"]
    assert sent == [
        {"type": "text", "text": copilot.PROMPTS[2], "cache_control": {"type": "ephemeral"}}
    ]
    assert "the approval card is the question" in copilot.PROMPTS[2]

    # a chat from before prompts were versioned keeps version 1
    old = AgentConversation(
        user_id=me["id"],
        title="old chat",
        model="claude-sonnet-5-5",
        effort="medium",
        messages=[{"role": "user", "content": "hi"}, {"role": "assistant", "content": "Hello!"}],
    )
    session.add(old)
    session.commit()
    _ask(client, h, "again", conversation_id=old.id)
    assert claude.requests[1]["system"][0]["text"] == copilot.PROMPTS[1]

    # adding a newer version later doesn't change a chat already under way
    monkeypatch.setitem(copilot.PROMPTS, 3, "a future prompt")
    monkeypatch.setattr(copilot, "CURRENT_PROMPT", 3)
    _ask(client, h, "and again", conversation_id=new["id"])
    assert claude.requests[2]["system"][0]["text"] == copilot.PROMPTS[2]


def test_no_database_transaction_is_open_while_claude_works(client, login, claude, session, stages):
    # a turn can take a minute; holding a connection (and a row lock) for it would let a few
    # busy chats use up the connection pool for the whole API
    h = login(Role.agent)
    d = _deal(client, h, stages[0], title="Renewal")
    seen = []

    def reply(result):
        def respond(_):
            seen.append(session.in_transaction())
            return result

        return respond

    claude.script = [
        reply(tool_call("get_deal", {"deal_id": d["id"]})),
        reply(
            tool_call(
                "propose_move_stage",
                {"deal_id": d["id"], "stage_id": stages[1], "reason": "Qualified"},
                "toolu_2",
            )
        ),
        reply(say("Proposed.")),
    ]
    view = _ask(client, h, "Move Renewal on").json()
    assert seen == [False, False, False]
    assert [p["status"] for p in view["proposals"]] == ["pending"]


def test_one_turn_at_a_time_per_conversation(client, login, claude, session):
    h = login(Role.agent)
    claude.script = [say("Hi")]
    conv = _ask(client, h, "Hello").json()
    row = session.get(AgentConversation, conv["id"])

    row.turn_started_at = utcnow()  # another tab is waiting for an answer
    session.add(row)
    session.commit()
    r = _ask(client, h, "And now?", conversation_id=conv["id"])
    assert r.status_code == 409 and "still answering" in r.json()["detail"]

    row.turn_started_at = utcnow() - timedelta(minutes=30)  # that server process died
    session.add(row)
    session.commit()
    claude.script = [say("Here")]
    assert _ask(client, h, "And now?", conversation_id=conv["id"]).status_code == 202
    session.refresh(row)
    assert row.turn_started_at is None


def test_failed_turn_withdraws_its_proposals_and_frees_the_chat(client, login, claude, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0], title="Expansion")

    def fail(_):
        raise anthropic.APIConnectionError(
            request=httpx2.Request("POST", "https://api.anthropic.com")
        )

    claude.script = [
        tool_call("propose_move_stage", {"deal_id": d["id"], "stage_id": stages[1], "reason": "x"}),
        fail,
    ]
    r = _ask(client, h, "Move Expansion on")
    assert r.status_code == 202
    conv = client.get(f"{API}/copilot/conversations/{r.json()['id']}", headers=h).json()
    # it says why, and gives back the message to send again; the failed turn isn't kept
    assert conv["running"] is False and conv["items"] == []
    assert conv["failure"] == {"message": turns.UNREACHABLE, "text": "Move Expansion on"}
    mine = client.get(f"{API}/proposals", headers=h).json()
    assert [(p["status"], p["error"]) for p in mine] == [
        ("failed", "Copilot's reply didn't finish, so this suggestion was withdrawn")
    ]
    claude.script = [say("Back")]
    view = _ask(client, h, "Try again", conversation_id=conv["id"]).json()
    assert [i["text"] for i in view["items"]] == ["Try again", "Back"]
    assert view["failure"] is None


def test_the_chat_shows_each_step_while_copilot_works(client, login, claude, session, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0], title="Fleet tracking")
    seen: list[ConversationView] = []

    def look(_: dict) -> dict:  # what someone reading the chat sees just before this call
        conv = session.exec(select(AgentConversation)).one()
        seen.append(copilot_routes._view(session, conv))
        return tool_call("get_deal", {"deal_id": d["id"]}) if len(seen) == 1 else say("Done")

    claude.script = [look, look]
    view = _ask(client, h, "How is Fleet tracking?").json()
    first, second = seen
    assert first.running and [i.text for i in first.items] == ["How is Fleet tracking?"]
    assert second.running and [(i.kind, i.text) for i in second.items] == [
        ("user", "How is Fleet tracking?"),
        ("step", "Read “Fleet tracking”"),
    ]
    assert view["running"] is False and view["items"][-1]["text"] == "Done"
    assert session.exec(select(AgentConversation)).one().turn_progress is None


def test_a_turn_whose_server_died_says_so(client, login, claude, session):
    h = login(Role.agent)
    claude.script = [say("Hi")]
    conv = _ask(client, h, "Hello").json()
    row = session.get(AgentConversation, conv["id"])
    row.turn_started_at = utcnow() - timedelta(minutes=30)
    row.turn_progress = [{"role": "user", "content": "Are you there?"}]
    session.add(row)
    session.commit()
    view = client.get(f"{API}/copilot/conversations/{conv['id']}", headers=h).json()
    assert view["running"] is False
    assert view["failure"] == {"message": turns.INTERRUPTED, "text": "Are you there?"}
    assert [i["text"] for i in view["items"]] == ["Hello", "Hi"]


def test_shutting_down_ends_the_turns_in_progress(client, login, claude, session, monkeypatch):
    h = login(Role.agent)
    claude.script = [say("Hi")]
    conv = _ask(client, h, "Hello").json()
    row = session.get(AgentConversation, conv["id"])
    row.turn_started_at = utcnow()
    row.turn_progress = [{"role": "user", "content": "Still there?"}]
    session.add(row)
    session.commit()
    session.refresh(row)
    monkeypatch.setattr(turns, "_running", {(conv["id"], row.turn_started_at)})
    monkeypatch.setattr(turns, "_pool", ThreadPoolExecutor(max_workers=1))
    turns.interrupt_all()
    session.refresh(row)
    assert row.turn_started_at is None
    assert row.turn_error == {"message": turns.INTERRUPTED, "text": "Still there?"}


def test_sending_doesnt_wait_for_the_answer(client, login, claude, monkeypatch):
    """The request returns while Copilot is still working, in a pool of its own."""
    h = login(Role.agent)
    release, answered = threading.Event(), threading.Event()

    def slow_answer(*_: object) -> None:
        release.wait(5)
        answered.set()

    pool = ThreadPoolExecutor(max_workers=1)
    monkeypatch.setattr(turns, "run_in_background", pool.submit)
    monkeypatch.setattr(turns, "_answer", slow_answer)
    r = _ask(client, h, "Hello")
    assert r.status_code == 202 and r.json()["running"] is True
    assert [i["text"] for i in r.json()["items"]] == ["Hello"]
    assert not answered.is_set()
    release.set()
    pool.shutdown(wait=True)
    assert answered.is_set()


def test_a_turn_that_was_replaced_leaves_the_new_one_alone(client, login, claude, session, stages):
    """A turn that ran past TURN_TIMEOUT can still be working when the person sends again. The
    new message takes the chat over; the old turn must then stop without writing anything."""
    h = login(Role.agent)
    d = _deal(client, h, stages[0], title="Warehouse")
    claude.script = [say("Hi")]
    conv_id = _ask(client, h, "Hello").json()["id"]
    newer = {"role": "user", "content": "Anyone there?"}

    def someone_sends_again(_: dict) -> dict:
        # what POST /copilot/messages does for a turn it has given up on
        row = session.get(AgentConversation, conv_id)
        turns.end_failed_turn(
            session, conv_id, row.turn_started_at, turns.INTERRUPTED, "x", commit=False
        )
        row.turn_started_at = utcnow()
        row.turn_progress = [newer]
        row.turn_error = None
        session.add(row)
        session.commit()
        return tool_call("propose_mark_won", {"deal_id": d["id"], "reason": "Signed"}, "toolu_2")

    claude.script = [
        tool_call("propose_move_stage", {"deal_id": d["id"], "stage_id": stages[1], "reason": "x"}),
        someone_sends_again,
        say("Never asked for"),
    ]
    assert _ask(client, h, "Move Warehouse on", conversation_id=conv_id).status_code == 202

    row = session.get(AgentConversation, conv_id)
    session.refresh(row)
    assert row.turn_progress == [newer] and row.turn_started_at is not None
    assert row.turn_error is None
    assert not turns._running  # it's no longer counted as running here
    assert [m["content"] for m in row.messages if m["role"] == "user"] == ["Hello"]
    assert len(claude.requests) == 3  # it stopped before asking Claude again
    # the proposal it made earlier was withdrawn; the one it made after being replaced is gone
    made = session.exec(select(AgentProposal).where(AgentProposal.conversation_id == conv_id))
    assert [(p.action, p.status) for p in made] == [("move_stage", "failed")]
    # both of its calls were billed (and the first message's)
    billed = session.exec(select(AIUsage).where(AIUsage.conversation_id == conv_id)).all()
    assert len(billed) == 3


def test_a_queued_turn_that_was_replaced_doesnt_run(client, login, claude, session):
    h = login(Role.agent)
    claude.script = [say("Hi")]
    conv_id = _ask(client, h, "Hello").json()["id"]
    row = session.get(AgentConversation, conv_id)
    queued_at = utcnow() - timedelta(minutes=30)
    row.turn_started_at = utcnow()  # a newer message took the chat while it waited
    session.add(row)
    session.commit()

    turns._answer(conv_id, row.user_id, "Old question", None, claude, queued_at)
    session.refresh(row)
    assert len(claude.requests) == 1 and row.turn_started_at is not None
    assert row.turn_error is None

    # nor does shutting down end that newer turn on the old one's behalf
    turns.end_failed_turn(session, conv_id, queued_at, turns.INTERRUPTED, "Old question")
    session.refresh(row)
    assert row.turn_started_at is not None and row.turn_error is None


def test_one_person_has_only_a_few_replies_under_way(client, login, claude, session, monkeypatch):
    monkeypatch.setattr(copilot.settings, "COPILOT_TURNS_PER_PERSON", 2)
    h = login(Role.agent)
    claude.script = [say("One"), say("Two")]
    chats = [_ask(client, h, text).json()["id"] for text in ("First", "Second")]
    rows = [session.get(AgentConversation, i) for i in chats]
    for row in rows:  # both still being answered, in other tabs
        row.turn_started_at = utcnow()
        session.add(row)
    session.commit()

    r = _ask(client, h, "Third")
    assert r.status_code == 429 and "other chats" in r.json()["detail"]
    # someone else isn't held up by it
    claude.script = [say("Yours")]
    assert _ask(client, login(Role.agent), "Mine").status_code == 202

    rows[0].turn_started_at = utcnow() - timedelta(minutes=30)  # that one died long ago
    session.add(rows[0])
    session.commit()
    claude.script = [say("Three")]
    assert _ask(client, h, "Third").status_code == 202


def test_claude_calls_have_a_time_limit(monkeypatch):
    monkeypatch.setattr(copilot.settings, "AI_ENABLED", True)
    monkeypatch.setattr(copilot.settings, "ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(copilot.settings, "CLAUDE_TIMEOUT_SECONDS", 90)
    client = copilot.get_client()
    assert client is not None
    assert client.timeout == 90 and client.max_retries == 2
    # retries included, a hung call gives up well inside a turn's time limit
    assert 3 * client.timeout < turns.TURN_TIMEOUT.total_seconds()
