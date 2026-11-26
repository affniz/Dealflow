"""Personal access tokens and the MCP server at /mcp."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import anyio
from sqlmodel import select

from app.core.config import settings
from app.mcp_server import server
from app.models import ApiToken, Role, User, utcnow
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
    # not offered the proposal tools, and refused if it calls one anyway
    tools = {t["name"] for t in _rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert "search_deals" in tools and not {t for t in tools if t.startswith("propose_")}
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


def test_token_names_are_trimmed_and_cant_be_blank(client, login):
    h = login(Role.agent)
    _token(client, h, "  Laptop  ")
    assert [t["name"] for t in client.get(f"{API}/users/me/tokens", headers=h).json()] == ["Laptop"]
    r = client.post(f"{API}/users/me/tokens", headers=h, json={"name": "   "})
    assert r.status_code == 422


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


def test_expired_tokens_stop_working_and_say_so(client, login, session, monkeypatch):
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
    # the date is the team's: 20:00 UTC on 1 Jan is already 2 Jan in India
    monkeypatch.setattr(settings, "TIMEZONE", "Asia/Kolkata")
    row.expires_at = datetime(2026, 1, 1, 20, 0, tzinfo=UTC)
    session.add(row)
    session.commit()
    assert "expired on 02 Jan 2026" in _rpc(client, token, "tools/list").json()["detail"]
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


def test_only_a_request_with_a_suggest_token_is_offered_proposals():
    # outside a request that came through the token check, the server offers the read tools only
    tools = {t.name for t in anyio.run(server.list_tools)}
    assert "search_deals" in tools
    assert not {t for t in tools if t.startswith("propose_")}


def test_hourly_cleanup_deletes_tokens_a_month_after_they_expire(client, login, session):
    from app.worker import purge_trash_job

    h = login(Role.agent)
    for name in ("Live", "Lately", "Long gone"):
        _token(client, h, name)
    now = utcnow()
    expired = {"Lately": now - timedelta(days=29), "Long gone": now - timedelta(days=31)}
    for row in session.exec(select(ApiToken)).all():
        if row.name in expired:
            row.expires_at = expired[row.name]
            session.add(row)
    session.commit()

    assert purge_trash_job(session)["expired_tokens"] == 1
    listed = {t["name"] for t in client.get(f"{API}/users/me/tokens", headers=h).json()}
    assert listed == {"Live", "Lately"}


def _expire_in(session, name: str, days: float, used: bool = True) -> None:
    row = session.exec(select(ApiToken).where(ApiToken.name == name)).one()
    row.expires_at = utcnow() + timedelta(days=days)
    row.last_used_at = utcnow() - timedelta(days=1) if used else None
    session.add(row)
    session.commit()


def _emails(smtp) -> list[tuple[Any, list[str]]]:
    return [s for s in smtp.sent if isinstance(s, tuple) and s[0] != "login"]  # type: ignore[misc]


def test_claude_is_told_in_a_tokens_last_week(client, login, session):
    h = login(Role.agent)
    token = _token(client, h, "Laptop")
    args = {"status": "open", "stalled_only": False, "mine_only": False, "limit": 5}
    err, out = _call(client, token, "search_deals", **args)
    assert not err and "notice" not in out

    _expire_in(session, "Laptop", days=3)
    err, out = _call(client, token, "search_deals", **args)
    assert not err and out["notice"].startswith("This access token stops working on ")


def test_people_are_emailed_once_before_a_token_they_use_expires(client, login, session, smtp):
    from app.worker import token_expiry_job

    smtp.enable()
    h = login(Role.agent, email="arjun@example.com")
    for name in ("Laptop", "Desktop", "Spare", "Later"):
        _token(client, h, name)
    _expire_in(session, "Laptop", days=3)
    _expire_in(session, "Desktop", days=6)
    _expire_in(session, "Spare", days=3, used=False)  # nothing stops working: no email
    _expire_in(session, "Later", days=10)
    # someone who has left isn't emailed about theirs
    _token(client, login(Role.agent, email="left@example.com"), "Old")
    _expire_in(session, "Old", days=3)
    left = session.exec(select(User).where(User.email == "left@example.com")).one()
    left.is_active = False
    session.add(left)
    session.commit()

    assert token_expiry_job(session) == {"emails_sent": 1}
    [(msg, to)] = _emails(smtp)
    assert to == ["arjun@example.com"]
    assert msg["Subject"] == "Dealflow: 2 of your access tokens expire soon"
    body = msg.get_content()
    assert "- Laptop (dfp_" in body and "- Desktop (dfp_" in body
    assert "Spare" not in body and "Later" not in body
    assert "https://crm.example.com/account#connect-claude" in body

    # once per token
    assert token_expiry_job(session) == {"skipped": "No tokens expiring this week"}
    assert len(_emails(smtp)) == 1


def test_expiry_emails_need_email_set_up_and_retry_failures(
    client, login, session, smtp, monkeypatch
):
    from app.services import api_tokens
    from app.worker import token_expiry_job

    _token(client, login(Role.agent), "Laptop")
    _expire_in(session, "Laptop", days=3)
    assert token_expiry_job(session) == {"skipped": "Email isn't set up"}

    smtp.enable()
    send_email = api_tokens.send_email
    monkeypatch.setattr(api_tokens, "send_email", lambda *_: False)  # the mail server is down
    result = token_expiry_job(session)
    assert result["emails_sent"] == 0 and "tried again next hour" in str(result["problem"])

    monkeypatch.setattr(api_tokens, "send_email", send_email)
    assert token_expiry_job(session) == {"emails_sent": 1}
