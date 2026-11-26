"""Personal access tokens and the MCP server at /mcp."""

import json
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import select

from app.models import ApiToken, Role, utcnow
from tests.conftest import API

HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def _token(client, h, name="Claude Code", **extra) -> str:
    r = client.post(f"{API}/users/me/tokens", headers=h, json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()["token"]


def _rpc(client, token: str | None, method: str, params: dict[str, Any] | None = None):
    headers = dict(HEADERS)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    return client.post("/mcp", headers=headers, json=body)


def _call(client, token: str, tool: str, **args) -> tuple[bool, Any]:
    """(is_error, parsed result) for a tools/call."""
    r = _rpc(client, token, "tools/call", {"name": tool, "arguments": args})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    text = result["content"][0]["text"]
    if result.get("isError"):
        return True, text
    return False, json.loads(text)


def _deal(client, h, stage_id, title="Deal", value=1000) -> int:
    r = client.post(
        f"{API}/deals", headers=h, json={"title": title, "value": value, "stage_id": stage_id}
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_tokens_are_shown_once_listed_and_revoked(client, login):
    h = login(Role.agent)
    token = _token(client, h)
    assert token.startswith("dfp_")
    listed = client.get(f"{API}/users/me/tokens", headers=h).json()
    assert len(listed) == 1
    assert listed[0]["name"] == "Claude Code"
    assert "token" not in listed[0] and token.startswith(listed[0]["prefix"])

    # someone else can't see or revoke it
    other = login(Role.admin)
    assert client.get(f"{API}/users/me/tokens", headers=other).json() == []
    tid = listed[0]["id"]
    assert client.delete(f"{API}/users/me/tokens/{tid}", headers=other).status_code == 404

    assert _rpc(client, token, "tools/list").status_code == 200
    assert client.delete(f"{API}/users/me/tokens/{tid}", headers=h).status_code == 200
    assert _rpc(client, token, "tools/list").status_code == 401


def test_mcp_refuses_missing_wrong_and_session_tokens(client, login):
    h = login(Role.agent)
    assert _rpc(client, None, "tools/list").status_code == 401
    assert _rpc(client, "dfp_not-a-real-token", "tools/list").status_code == 401
    # a sign-in (JWT) token is for the web app only
    jwt = h["Authorization"].removeprefix("Bearer ")
    assert _rpc(client, jwt, "tools/list").status_code == 401


def test_deactivated_users_token_stops_working(client, login, session):
    admin = login(Role.admin)
    h = login(Role.agent, email="leaving@example.com")
    token = _token(client, h)
    me = client.get(f"{API}/users/me", headers=h).json()
    client.patch(f"{API}/users/{me['id']}", headers=admin, json={"is_active": False})
    assert _rpc(client, token, "tools/list").status_code == 401


def test_initialize_and_list_tools(client, login):
    token = _token(client, login(Role.agent), scope="suggest")
    r = _rpc(
        client,
        token,
        "initialize",
        {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert r.status_code == 200, r.text
    info = r.json()["result"]
    assert info["serverInfo"]["name"] == "Dealflow"
    assert "Agent inbox" in info["instructions"]

    tools = {t["name"]: t for t in _rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert {"search_deals", "get_deal", "pipeline_overview", "propose_move_stage"} <= set(tools)
    assert tools["search_deals"]["annotations"]["readOnlyHint"] is True
    assert tools["propose_mark_won"]["annotations"]["readOnlyHint"] is False
    # arguments are the tool's fields at the top level; null ones can be left out
    schema = tools["search_deals"]["inputSchema"]
    assert "query" in schema["properties"] and "query" not in schema["required"]
    assert "status" in schema["required"]


def test_read_tools_follow_the_tokens_access(client, login, stages):
    mine = login(Role.agent)
    theirs = login(Role.agent)
    _deal(client, mine, stages[0], "Tata Steel renewal")
    _deal(client, theirs, stages[0], "Infosys expansion")
    token = _token(client, mine)

    err, out = _call(
        client, token, "search_deals", status="any", stalled_only=False, mine_only=False, limit=50
    )
    assert not err
    assert [d["title"] for d in out["deals"]] == ["Tata Steel renewal"]

    hidden = client.get(f"{API}/deals", headers=theirs).json()["data"][0]["id"]
    err, text = _call(client, token, "get_deal", deal_id=hidden)
    assert err and "isn't visible" in text


def test_change_tools_create_proposals_for_the_inbox(client, login, stages):
    h = login(Role.agent)
    deal_id = _deal(client, h, stages[0], "Wipro pilot")
    token = _token(client, h, scope="suggest")

    err, out = _call(
        client,
        token,
        "propose_move_stage",
        deal_id=deal_id,
        stage_id=stages[1],
        reason="They confirmed budget on today's call",
    )
    assert not err and out["status"] == "pending approval"

    # nothing changed yet; the proposal waits in the inbox, marked as coming from MCP
    assert client.get(f"{API}/deals/{deal_id}", headers=h).json()["stage_id"] == stages[0]
    pending = client.get(f"{API}/proposals", headers=h, params={"status": "pending"}).json()
    assert [(p["source"], p["deal_id"]) for p in pending] == [("mcp", deal_id)]

    r = client.post(f"{API}/proposals/{pending[0]['id']}/approve", headers=h)
    assert r.json()["status"] == "approved"
    assert client.get(f"{API}/deals/{deal_id}", headers=h).json()["stage_id"] == stages[1]


def test_viewer_can_read_but_not_propose(client, login, stages):
    agent = login(Role.agent)
    deal_id = _deal(client, agent, stages[0])
    token = _token(client, login(Role.viewer), scope="suggest")  # the role still decides
    err, out = _call(
        client, token, "search_deals", status="open", stalled_only=False, mine_only=False, limit=5
    )
    assert not err and len(out["deals"]) == 1
    err, text = _call(client, token, "propose_mark_won", deal_id=deal_id, reason="Signed")
    assert err and "viewer" in text


def test_invalid_arguments_are_reported_to_the_client(client, login):
    token = _token(client, login(Role.agent))
    r = _rpc(client, token, "tools/call", {"name": "get_deal", "arguments": {"deal_id": "x"}})
    assert r.status_code == 200
    body = r.json()
    assert body.get("error") or body["result"]["isError"]


def test_new_tokens_read_only_for_ninety_days_unless_asked(client, login):
    h = login(Role.agent)
    _token(client, h, "Default")
    _token(client, h, "Script", scope="suggest", expires_in_days=30)
    listed = {t["name"]: t for t in client.get(f"{API}/users/me/tokens", headers=h).json()}
    assert listed["Default"]["scope"] == "read"
    assert listed["Script"]["scope"] == "suggest"

    def days_left(t):
        expires = datetime.fromisoformat(t["expires_at"])
        return round((expires - datetime.fromisoformat(t["created_at"])).total_seconds() / 86400)

    assert days_left(listed["Default"]) == 90
    assert days_left(listed["Script"]) == 30

    for bad in ({"expires_in_days": 1000}, {"expires_in_days": None}, {"scope": "write"}):
        r = client.post(f"{API}/users/me/tokens", headers=h, json={"name": "Bad", **bad})
        assert r.status_code == 422, bad


def test_read_only_tokens_arent_offered_or_allowed_to_propose(client, login, stages):
    h = login(Role.agent)
    deal_id = _deal(client, h, stages[0])
    token = _token(client, h)  # read only

    tools = {t["name"] for t in _rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert "search_deals" in tools
    assert not {t for t in tools if t.startswith("propose_")}

    # even when a client calls one anyway
    err, text = _call(
        client, token, "propose_move_stage", deal_id=deal_id, stage_id=stages[1], reason="Go"
    )
    assert err and "can only read" in text
    assert client.get(f"{API}/proposals", headers=h, params={"status": "pending"}).json() == []


def test_expired_tokens_stop_working_and_say_so(client, login, session):
    h = login(Role.agent)
    token = _token(client, h)
    assert _rpc(client, token, "tools/list").status_code == 200

    row = session.exec(select(ApiToken)).one()
    row.expires_at = utcnow() - timedelta(minutes=1)
    session.add(row)
    session.commit()

    r = _rpc(client, token, "tools/list")
    assert r.status_code == 401
    assert r.json()["detail"].startswith("This access token expired on ")
    # still listed, so the person can see what happened and revoke it
    [listed] = client.get(f"{API}/users/me/tokens", headers=h).json()
    assert datetime.fromisoformat(listed["expires_at"]) < utcnow()


def test_expired_tokens_dont_count_toward_the_limit(client, login, session, monkeypatch):
    from app.api.routes import tokens

    monkeypatch.setattr(tokens, "MAX_TOKENS", 2)
    h = login(Role.agent)
    _token(client, h, "One")
    _token(client, h, "Two")
    r = client.post(f"{API}/users/me/tokens", headers=h, json={"name": "Three"})
    assert r.status_code == 409

    old = session.exec(select(ApiToken).where(ApiToken.name == "One")).one()
    old.expires_at = utcnow() - timedelta(days=1)
    session.add(old)
    session.commit()
    _token(client, h, "Three")
