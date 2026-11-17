from datetime import timedelta

from app.models import Deal, Role, utcnow
from app.services.rotting import check_rotting
from tests.conftest import API


def _deal(client, h, stage_id, title="Deal", value=1000):
    r = client.post(
        f"{API}/deals", headers=h, json={"title": title, "value": value, "stage_id": stage_id}
    )
    assert r.status_code == 201, r.text
    return r.json()


def _age(session, deal_id, days):
    """Pretend the deal entered its current stage `days` ago."""
    deal = session.get(Deal, deal_id)
    deal.stage_changed_at = utcnow() - timedelta(days=days)
    session.add(deal)
    session.commit()


def _pipeline_id(client, h):
    return client.get(f"{API}/pipelines", headers=h).json()[0]["id"]


# ---------------------------------------------------------------- rotting deals


def test_stale_deal_is_flagged_once_with_follow_up_task(client, login, session, stages):
    h = login(Role.agent)
    stale = _deal(client, h, stages[0], title="Stale")
    fresh = _deal(client, h, stages[0], title="Fresh")
    _age(session, stale["id"], 20)  # default pipeline rots after 14 days
    _age(session, fresh["id"], 5)

    assert check_rotting(session).flagged == 1
    assert check_rotting(session).flagged == 0  # idempotent: no duplicate tasks

    assert client.get(f"{API}/deals/{stale['id']}", headers=h).json()["is_rotting"] is True
    assert client.get(f"{API}/deals/{fresh['id']}", headers=h).json()["is_rotting"] is False
    rotting = client.get(f"{API}/deals", headers=h, params={"rotting": True}).json()
    assert [d["title"] for d in rotting["data"]] == ["Stale"]

    tasks = client.get(f"{API}/activities", headers=h, params={"deal_id": stale["id"]}).json()
    assert [t["subject"] for t in tasks["data"]] == ["Stalled deal: Stale"]
    timeline = client.get(f"{API}/deals/{stale['id']}/timeline", headers=h).json()
    rot = [i["event"] for i in timeline if i["kind"] == "event" and i["event"]["kind"] == "rotting"]
    assert rot[0]["data"]["days_in_stage"] == 20 and rot[0]["actor_id"] is None


def test_moving_or_closing_clears_the_flag(client, login, session, stages):
    h = login(Role.agent)
    moved, won = _deal(client, h, stages[0]), _deal(client, h, stages[0])
    for d in (moved, won):
        _age(session, d["id"], 30)
    check_rotting(session)

    r = client.patch(f"{API}/deals/{moved['id']}", headers=h, json={"stage_id": stages[1]})
    assert r.json()["is_rotting"] is False
    assert client.post(f"{API}/deals/{won['id']}/won", headers=h).json()["is_rotting"] is False


def test_closed_deals_never_rot(client, login, session, stages):
    h = login(Role.agent)
    d = _deal(client, h, stages[0])
    client.post(f"{API}/deals/{d['id']}/won", headers=h)
    _age(session, d["id"], 60)
    assert check_rotting(session).flagged == 0


def test_raising_rotting_days_clears_flags(client, login, session, stages):
    admin = login(Role.admin)
    d = _deal(client, admin, stages[0])
    _age(session, d["id"], 20)
    check_rotting(session)
    pid = _pipeline_id(client, admin)
    client.patch(f"{API}/pipelines/{pid}", headers=admin, json={"rotting_days": 30})
    assert check_rotting(session).cleared == 1
    assert client.get(f"{API}/deals/{d['id']}", headers=admin).json()["is_rotting"] is False


# ---------------------------------------------------------------- board


def test_board_columns_totals_and_cap(client, login, session, stages):
    alice, bob = login(Role.agent), login(Role.agent)
    for v in (1000, 2000, 3000):
        _deal(client, alice, stages[2], value=v)  # Proposal, 50%
    _deal(client, bob, stages[2], value=99999)
    rotten = _deal(client, alice, stages[0], value=500)
    _age(session, rotten["id"], 20)
    check_rotting(session)

    board = client.get(
        f"{API}/pipelines/{_pipeline_id(client, alice)}/board",
        headers=alice,
        params={"deals_per_stage": 2},
    ).json()
    assert [c["stage"]["name"] for c in board["columns"]] == [
        "Lead",
        "Qualified",
        "Proposal",
        "Negotiation",
    ]
    proposal = board["columns"][2]
    # totals cover all of alice's deals in the stage even though only 2 are listed
    assert proposal["deal_count"] == 3 and len(proposal["deals"]) == 2
    assert proposal["total_value"] == "6000.00" and proposal["weighted_value"] == "3000.00"
    lead = board["columns"][0]
    assert lead["rotting_count"] == 1 and lead["deals"][0]["is_rotting"] is True
    assert board["columns"][3]["total_value"] == "0.00"  # empty column, still 2 dp
    assert board["total_value"] == "6500.00" and board["weighted_value"] == "3050.00"


# ---------------------------------------------------------------- lost-reason analytics


def test_lost_reason_report(client, login, session, stages):
    alice, bob, admin = login(Role.agent), login(Role.agent), login(Role.admin)
    reasons = {r["label"]: r["id"] for r in client.get(f"{API}/lost-reasons", headers=admin).json()}

    def lose(h, value, label):
        d = _deal(client, h, stages[1], value=value)
        body = {"lost_reason_id": reasons[label]}
        assert client.post(f"{API}/deals/{d['id']}/lost", headers=h, json=body).status_code == 200
        return d

    lose(alice, 1000, "Price")
    lose(alice, 2000, "Price")
    lose(bob, 5000, "No budget")
    old = lose(bob, 7000, "Price")
    deal = session.get(Deal, old["id"])
    deal.closed_at = utcnow() - timedelta(days=200)  # outside the default 90-day window
    session.add(deal)
    session.commit()

    r = client.get(f"{API}/dashboard/lost-reasons", headers=admin).json()
    assert r["lost_count"] == 3 and r["lost_value"] == "8000.00"
    assert [(x["label"], x["count"], x["value"]) for x in r["reasons"]] == [
        ("Price", 2, "3000.00"),
        ("No budget", 1, "5000.00"),
    ]
    assert r["reasons"][0]["share"] == 0.6667

    year = client.get(f"{API}/dashboard/lost-reasons", headers=admin, params={"days": 365}).json()
    assert year["lost_count"] == 4

    # agents only see their own losses
    mine = client.get(f"{API}/dashboard/lost-reasons", headers=alice).json()
    assert mine["lost_count"] == 2 and [x["label"] for x in mine["reasons"]] == ["Price"]
