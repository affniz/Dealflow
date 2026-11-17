from app.models import Role
from tests.conftest import API


def _deal(client, h, stage_id, title="Deal", value=1000):
    r = client.post(
        f"{API}/deals", headers=h, json={"title": title, "value": value, "stage_id": stage_id}
    )
    assert r.status_code == 201, r.text
    return r.json()


def test_create_deal_takes_pipeline_from_stage(client, login, stages):
    d = _deal(client, login(Role.agent), stages[0])
    assert d["status"] == "open" and d["currency"] == "INR" and d["pipeline_id"]
    assert d["value"] == "1000.00"


def test_unknown_stage_is_rejected(client, login):
    body = {"title": "x", "stage_id": 999}
    assert client.post(f"{API}/deals", headers=login(Role.agent), json=body).status_code == 422


def test_moving_stage_is_recorded_on_timeline(client, login, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0])
    r = client.patch(f"{API}/deals/{d['id']}", headers=h, json={"stage_id": stages[2], "value": 5})
    assert r.json()["stage_id"] == stages[2]
    assert r.json()["stage_changed_at"] >= d["stage_changed_at"]
    client.post(
        f"{API}/activities", headers=h, json={"type": "note", "subject": "Hi", "deal_id": d["id"]}
    )

    timeline = client.get(f"{API}/deals/{d['id']}/timeline", headers=h).json()
    kinds = [i["event"]["kind"] if i["kind"] == "event" else "activity" for i in timeline]
    assert sorted(kinds) == ["activity", "created", "stage_changed", "updated"]
    events = [i["event"] for i in timeline if i["kind"] == "event"]
    moved = next(e for e in events if e["kind"] == "stage_changed")
    assert moved["data"] == {"from_stage_id": stages[0], "to_stage_id": stages[2]}


def test_won_lost_reopen(client, login, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0])
    reasons = client.get(f"{API}/lost-reasons", headers=h).json()

    bad = {"lost_reason_id": 999}
    assert client.post(f"{API}/deals/{d['id']}/lost", headers=h, json=bad).status_code == 422
    body = {"lost_reason_id": reasons[0]["id"], "note": "Too expensive"}
    lost = client.post(f"{API}/deals/{d['id']}/lost", headers=h, json=body).json()
    assert lost["status"] == "lost" and lost["lost_reason_id"] == reasons[0]["id"]

    assert client.post(f"{API}/deals/{d['id']}/won", headers=h).status_code == 409
    move = {"stage_id": stages[1]}
    assert client.patch(f"{API}/deals/{d['id']}", headers=h, json=move).status_code == 409

    reopened = client.post(f"{API}/deals/{d['id']}/reopen", headers=h).json()
    assert reopened["status"] == "open" and reopened["lost_reason_id"] is None
    won = client.post(f"{API}/deals/{d['id']}/won", headers=h).json()
    assert won["status"] == "won" and won["closed_at"]


def test_dashboard_weighted_totals(client, login, stages):
    alice, bob, admin = login(Role.agent), login(Role.agent), login(Role.admin)
    _deal(client, alice, stages[0], value=1000)  # Lead 10%   -> 100
    _deal(client, alice, stages[2], value=2000)  # Proposal 50% -> 1000
    _deal(client, bob, stages[2], value=4000)  # Proposal 50% -> 2000
    won = _deal(client, bob, stages[3], value=9000)
    client.post(f"{API}/deals/{won['id']}/won", headers=bob)

    pipeline_id = client.get(f"{API}/pipelines", headers=admin).json()[0]["id"]
    s = client.get(f"{API}/dashboard/pipeline/{pipeline_id}", headers=admin).json()
    assert s["open_count"] == 3
    assert s["open_value"] == "7000.00"
    assert s["weighted_value"] == "3100.00"
    assert s["won_count"] == 1 and s["won_value"] == "9000.00"
    proposal = next(st for st in s["stages"] if st["name"] == "Proposal")
    assert proposal["deal_count"] == 2 and proposal["weighted_value"] == "3000.00"

    # agents only see their own numbers
    mine = client.get(f"{API}/dashboard/pipeline/{pipeline_id}", headers=alice).json()
    assert mine["open_value"] == "3000.00" and mine["won_count"] == 0


def test_pipeline_admin(client, login, stages):
    admin, agent = login(Role.admin), login(Role.agent)
    body = {"name": "Partners", "stages": [{"name": "Intro", "position": 0, "probability": 20}]}
    assert client.post(f"{API}/pipelines", headers=agent, json=body).status_code == 403
    p = client.post(f"{API}/pipelines", headers=admin, json=body).json()
    assert [s["name"] for s in p["stages"]] == ["Intro"]
    assert client.post(f"{API}/pipelines", headers=admin, json=body).status_code == 409

    _deal(client, agent, stages[0])
    assert client.delete(f"{API}/stages/{stages[0]}", headers=admin).status_code == 409
    assert client.delete(f"{API}/stages/{p['stages'][0]['id']}", headers=admin).status_code == 204


def test_dashboard_rounds_half_up(client, login, stages):
    h = login(Role.agent)
    _deal(client, h, stages[1], value="250000.50")  # Qualified 25% -> 62500.125
    pipeline_id = client.get(f"{API}/pipelines", headers=h).json()[0]["id"]
    s = client.get(f"{API}/dashboard/pipeline/{pipeline_id}", headers=h).json()
    assert s["weighted_value"] == "62500.13"


def test_deal_responses_include_names(client, login, stages):
    h = login(Role.agent, email="ravi@example.com")
    client.patch(f"{API}/users/me", headers=h, json={"full_name": "Ravi Kumar"})
    co = client.post(f"{API}/companies", headers=h, json={"name": "Infosys"}).json()
    c = client.post(
        f"{API}/contacts", headers=h, json={"first_name": "Priya", "last_name": "Shah"}
    ).json()
    body = {
        "title": "Renewal",
        "stage_id": stages[0],
        "company_id": co["id"],
        "contact_id": c["id"],
    }
    d = client.post(f"{API}/deals", headers=h, json=body).json()
    assert d["owner"]["name"] == "Ravi Kumar"
    assert d["company"] == {"id": co["id"], "name": "Infosys"}
    assert d["contact"]["name"] == "Priya Shah"

    listed = client.get(f"{API}/deals", headers=h).json()["data"][0]
    assert listed["company"]["name"] == "Infosys"
    board = client.get(f"{API}/pipelines/{d['pipeline_id']}/board", headers=h).json()
    assert board["columns"][0]["deals"][0]["contact"]["name"] == "Priya Shah"

    timeline = client.get(f"{API}/deals/{d['id']}/timeline", headers=h).json()
    assert timeline[0]["actor"]["name"] == "Ravi Kumar"


def test_user_directory_is_readable_by_everyone(client, login):
    viewer = login(Role.viewer)
    entries = client.get(f"{API}/users/directory", headers=viewer).json()
    assert {"owner", "viewer"} <= {e["role"] for e in entries}
    assert all(set(e) == {"id", "name", "role"} for e in entries)  # no emails or flags leak
