"""Dashboard summary filters and win rate; pipeline and stage settings."""

from datetime import timedelta

from app.models import Deal, Role, utcnow
from tests.conftest import API


def _deal(client, h, stage_id, value=1000, **extra):
    body = {"title": "D", "stage_id": stage_id, "value": str(value), **extra}
    r = client.post(f"{API}/deals", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def _pipeline_id(client, h):
    return client.get(f"{API}/pipelines", headers=h).json()[0]["id"]


def test_summary_win_rate_period_and_owner(client, login, session, stages):
    admin, alice, bob = login(Role.admin), login(Role.agent), login(Role.agent)
    alice_id = client.get(f"{API}/users/me", headers=alice).json()["id"]
    reason = client.get(f"{API}/lost-reasons", headers=admin).json()[0]["id"]

    for h, value in ((alice, 1000), (alice, 3000), (bob, 5000)):
        d = _deal(client, h, stages[1], value=value)
        client.post(f"{API}/deals/{d['id']}/won", headers=h)
    lost = _deal(client, alice, stages[1], value=2000)
    client.post(f"{API}/deals/{lost['id']}/lost", headers=alice, json={"lost_reason_id": reason})
    old = _deal(client, bob, stages[1], value=9000)
    client.post(f"{API}/deals/{old['id']}/won", headers=bob)
    deal = session.get(Deal, old["id"])
    deal.closed_at = utcnow() - timedelta(days=200)
    session.add(deal)
    session.commit()
    _deal(client, alice, stages[0], value=700)  # still open

    url = f"{API}/dashboard/pipeline/{_pipeline_id(client, admin)}"
    everything = client.get(url, headers=admin).json()
    assert everything["won_count"] == 4 and everything["since"] is None

    quarter = client.get(url, headers=admin, params={"days": 90}).json()
    assert quarter["won_count"] == 3 and quarter["won_value"] == "9000.00"
    assert quarter["lost_count"] == 1 and quarter["lost_value"] == "2000.00"
    assert quarter["win_rate"] == 0.75
    assert quarter["open_count"] == 1 and quarter["open_value"] == "700.00"

    hers = client.get(url, headers=admin, params={"days": 90, "owner_id": alice_id}).json()
    assert (hers["won_count"], hers["lost_count"], hers["win_rate"]) == (2, 1, 0.6667)

    # nothing closed: no win rate rather than 0%
    fresh = client.get(url, headers=login(Role.agent), params={"days": 90}).json()
    assert fresh["win_rate"] is None


def test_stage_order_and_new_stage_goes_last(client, login):
    admin = login(Role.admin)
    pid = _pipeline_id(client, admin)
    ids = [s["id"] for s in client.get(f"{API}/pipelines/{pid}", headers=admin).json()["stages"]]

    added = client.post(
        f"{API}/pipelines/{pid}/stages", headers=admin, json={"name": "Contract", "probability": 90}
    ).json()
    assert added["position"] == len(ids)

    order = [added["id"], *reversed(ids)]
    r = client.put(f"{API}/pipelines/{pid}/stage-order", headers=admin, json={"stage_ids": order})
    assert r.status_code == 200
    assert [s["id"] for s in r.json()["stages"]] == order

    # a partial or foreign list is refused, and agents can't reorder
    bad = {"stage_ids": order[:-1]}
    assert (
        client.put(f"{API}/pipelines/{pid}/stage-order", headers=admin, json=bad).status_code == 422
    )
    agent = login(Role.agent)
    body = {"stage_ids": order}
    assert (
        client.put(f"{API}/pipelines/{pid}/stage-order", headers=agent, json=body).status_code
        == 403
    )
