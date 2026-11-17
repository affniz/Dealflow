from app.models import Role
from tests.conftest import API


def test_agents_see_only_their_own_records(client, login):
    alice, bob, admin = login(Role.agent), login(Role.agent), login(Role.admin)
    c = client.post(f"{API}/contacts", headers=alice, json={"first_name": "Priya"}).json()

    assert client.get(f"{API}/contacts", headers=alice).json()["count"] == 1
    assert client.get(f"{API}/contacts", headers=bob).json()["count"] == 0
    assert client.get(f"{API}/contacts", headers=admin).json()["count"] == 1
    # someone else's record looks like it doesn't exist
    assert client.get(f"{API}/contacts/{c['id']}", headers=bob).status_code == 404
    patch = {"first_name": "X"}
    assert client.patch(f"{API}/contacts/{c['id']}", headers=bob, json=patch).status_code == 404


def test_viewers_are_read_only(client, login):
    viewer = login(Role.viewer)
    client.post(f"{API}/companies", headers=login(Role.agent), json={"name": "Acme"})
    assert client.get(f"{API}/companies", headers=viewer).json()["count"] == 1
    r = client.post(f"{API}/companies", headers=viewer, json={"name": "Nope"})
    assert r.status_code == 403


def test_agents_cannot_assign_records_to_others(client, login, session):
    agent, admin = login(Role.agent), login(Role.admin)
    other = client.get(f"{API}/users/me", headers=login(Role.agent)).json()["id"]
    body = {"name": "Acme", "owner_id": other}
    assert client.post(f"{API}/companies", headers=agent, json=body).status_code == 403
    r = client.post(f"{API}/companies", headers=admin, json=body)
    assert r.status_code == 201 and r.json()["owner_id"] == other


def test_cannot_link_to_invisible_company(client, login):
    alice, bob = login(Role.agent), login(Role.agent)
    co = client.post(f"{API}/companies", headers=alice, json={"name": "Acme"}).json()
    body = {"first_name": "Ravi", "company_id": co["id"]}
    assert client.post(f"{API}/contacts", headers=bob, json=body).status_code == 422
    assert client.post(f"{API}/contacts", headers=alice, json=body).status_code == 201


def test_search_and_custom_fields(client, login):
    h = login(Role.agent)
    client.post(
        f"{API}/contacts",
        headers=h,
        json={"first_name": "Priya", "email": "priya@acme.in", "custom_fields": {"city": "Pune"}},
    )
    client.post(f"{API}/contacts", headers=h, json={"first_name": "Ravi"})
    r = client.get(f"{API}/contacts", headers=h, params={"q": "acme"}).json()
    assert r["count"] == 1 and r["data"][0]["custom_fields"] == {"city": "Pune"}


def test_patch_rejects_null_for_required_fields(client, login):
    h = login(Role.agent)
    c = client.post(f"{API}/contacts", headers=h, json={"first_name": "Priya"}).json()
    r = client.patch(f"{API}/contacts/{c['id']}", headers=h, json={"first_name": None})
    assert r.status_code == 422


def test_deleting_company_keeps_contacts(client, login):
    h = login(Role.agent)
    co = client.post(f"{API}/companies", headers=h, json={"name": "Acme"}).json()
    c = client.post(
        f"{API}/contacts", headers=h, json={"first_name": "Priya", "company_id": co["id"]}
    ).json()
    assert client.delete(f"{API}/companies/{co['id']}", headers=h).status_code == 204
    assert client.get(f"{API}/contacts/{c['id']}", headers=h).json()["company_id"] is None


def test_overdue_activities(client, login):
    h = login(Role.agent)
    past = {"type": "call", "subject": "Follow up", "due_at": "2020-01-01T10:00:00+05:30"}
    client.post(f"{API}/activities", headers=h, json=past)
    future = {"type": "task", "subject": "Later", "due_at": "2099-01-01T00:00:00Z"}
    client.post(f"{API}/activities", headers=h, json=future)
    r = client.get(f"{API}/activities", headers=h, params={"overdue": True}).json()
    assert [a["subject"] for a in r["data"]] == ["Follow up"]
    # timezone-aware input is stored as UTC
    assert r["data"][0]["due_at"] == "2020-01-01T04:30:00Z"
