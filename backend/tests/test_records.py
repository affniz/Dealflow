from app.models import Role
from tests.conftest import API


def test_agents_see_the_whole_address_book_but_change_only_their_own(client, login, stages):
    alice, bob, admin, viewer = (
        login(Role.agent),
        login(Role.agent),
        login(Role.admin),
        login(Role.viewer),
    )
    acme = client.post(f"{API}/companies", headers=alice, json={"name": "Acme"}).json()
    body = {"first_name": "Priya", "company_id": acme["id"]}
    priya = client.post(f"{API}/contacts", headers=alice, json=body).json()

    # everyone finds them, and the API says who may change them
    for h, editable in ((alice, True), (bob, False), (admin, True), (viewer, False)):
        found = client.get(f"{API}/contacts", headers=h, params={"q": "priya"}).json()
        assert [(c["id"], c["can_edit"]) for c in found["data"]] == [(priya["id"], editable)]
        company = client.get(f"{API}/companies/{acme['id']}", headers=h).json()
        assert company["can_edit"] is editable and company["contact_count"] == 1
    assert client.get(f"{API}/contacts/{priya['id']}/history", headers=bob).status_code == 200

    # but only the owner and admins change or delete them
    for path in (f"contacts/{priya['id']}", f"companies/{acme['id']}"):
        r = client.patch(f"{API}/{path}", headers=bob, json={"notes": "x"})
        assert r.status_code == 403 and "owner or an admin" in r.json()["detail"]
        assert client.delete(f"{API}/{path}", headers=bob).status_code == 403
    r = client.patch(f"{API}/contacts/{priya['id']}", headers=admin, json={"job_title": "CFO"})
    assert r.status_code == 200

    # Bob links his own deal and call to them instead of adding duplicates
    deal = {"title": "Bob's Acme deal", "value": 500, "stage_id": stages[0]}
    deal |= {"company_id": acme["id"], "contact_id": priya["id"]}
    bobs = client.post(f"{API}/deals", headers=bob, json=deal)
    assert bobs.status_code == 201, bobs.text
    assert bobs.json()["company"]["name"] == "Acme"
    call = {"type": "call", "subject": "Intro call", "contact_id": priya["id"], "done": True}
    assert client.post(f"{API}/activities", headers=bob, json=call).status_code == 201

    # deals and activities stay private: each sees only their own on the shared records
    alices = {"title": "Alice's Acme deal", "value": 900, "stage_id": stages[0]}
    alices |= {"company_id": acme["id"]}
    alices = client.post(f"{API}/deals", headers=alice, json=alices).json()
    note = {"type": "note", "subject": "Private note", "contact_id": priya["id"]}
    client.post(f"{API}/activities", headers=alice, json=note)
    assert client.get(f"{API}/deals/{alices['id']}", headers=bob).status_code == 404
    as_bob = client.get(f"{API}/companies/{acme['id']}", headers=bob).json()
    as_admin = client.get(f"{API}/companies/{acme['id']}", headers=admin).json()
    assert (as_bob["open_deal_count"], as_admin["open_deal_count"]) == (1, 2)
    on_priya = client.get(f"{API}/activities", headers=bob, params={"contact_id": priya["id"]})
    assert [a["subject"] for a in on_priya.json()["data"]] == ["Intro call"]


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


def test_links_must_point_at_records_the_user_can_see(client, login, stages):
    alice, bob = login(Role.agent), login(Role.agent)
    co = client.post(f"{API}/companies", headers=alice, json={"name": "Acme"}).json()
    body = {"first_name": "Ravi", "company_id": co["id"]}
    # a teammate's company is in the shared address book
    assert client.post(f"{API}/contacts", headers=bob, json=body).status_code == 201
    # a teammate's deal isn't
    deal = {"title": "Alice's deal", "value": 100, "stage_id": stages[0]}
    deal = client.post(f"{API}/deals", headers=alice, json=deal).json()
    note = {"type": "note", "subject": "Hi", "deal_id": deal["id"]}
    assert client.post(f"{API}/activities", headers=bob, json=note).status_code == 422
    # nor is a company in the trash
    assert client.delete(f"{API}/companies/{co['id']}", headers=alice).status_code == 204
    assert client.post(f"{API}/contacts", headers=alice, json=body).status_code == 422


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
