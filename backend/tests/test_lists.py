"""Contact, company and activity lists: search, filters, sorting and linked names."""

from app.models import Role
from tests.conftest import API


def _me(client, h):
    return client.get(f"{API}/users/me", headers=h).json()["id"]


def test_contact_search_matches_full_name_and_company(client, login):
    h = login(Role.agent)
    co = client.post(f"{API}/companies", headers=h, json={"name": "Tata Steel"}).json()
    client.post(
        f"{API}/contacts",
        headers=h,
        json={"first_name": "Priya", "last_name": "Sharma", "company_id": co["id"]},
    )
    client.post(f"{API}/contacts", headers=h, json={"first_name": "Ravi"})

    def names(q):
        r = client.get(f"{API}/contacts", headers=h, params={"q": q}).json()
        return [c["first_name"] for c in r["data"]]

    assert names("priya sharma") == ["Priya"]
    assert names("tata") == ["Priya"]
    assert names("ravi") == ["Ravi"]


def test_contacts_carry_names_and_visible_open_deals(client, login, stages):
    admin, alice = login(Role.admin), login(Role.agent)
    alice_id = _me(client, alice)
    co = client.post(f"{API}/companies", headers=alice, json={"name": "Acme"}).json()
    c = client.post(
        f"{API}/contacts", headers=alice, json={"first_name": "Priya", "company_id": co["id"]}
    ).json()
    assert c["company"] == {"id": co["id"], "name": "Acme"}
    assert c["owner"]["id"] == alice_id

    deal = {"title": "Licence", "stage_id": stages[0], "contact_id": c["id"], "value": "1000"}
    client.post(f"{API}/deals", headers=alice, json=deal)
    won = client.post(f"{API}/deals", headers=alice, json=deal).json()
    client.post(f"{API}/deals/{won['id']}/won", headers=alice)
    # an admin's deal for the same contact: the admin counts it, Alice can't see it
    client.post(f"{API}/deals", headers=admin, json=deal)

    assert client.get(f"{API}/contacts/{c['id']}", headers=alice).json()["open_deal_count"] == 1
    assert client.get(f"{API}/contacts/{c['id']}", headers=admin).json()["open_deal_count"] == 2


def test_company_totals(client, login, stages):
    h = login(Role.agent)
    co = client.post(f"{API}/companies", headers=h, json={"name": "Acme"}).json()
    for name in ("Priya", "Ravi"):
        client.post(f"{API}/contacts", headers=h, json={"first_name": name, "company_id": co["id"]})
    for value in ("1000", "2500.50"):
        body = {"title": "D", "stage_id": stages[0], "company_id": co["id"], "value": value}
        client.post(f"{API}/deals", headers=h, json=body)

    row = client.get(f"{API}/companies", headers=h).json()["data"][0]
    assert row["contact_count"] == 2
    assert row["open_deal_count"] == 2
    assert row["open_deal_value"] == "3500.50"


def test_company_search_and_sort(client, login):
    h = login(Role.agent)
    for body in (
        {"name": "zeta Labs", "industry": "Software"},
        {"name": "Alpha Foods", "domain": "alpha.in"},
    ):
        client.post(f"{API}/companies", headers=h, json=body)

    def names(**params):
        r = client.get(f"{API}/companies", headers=h, params=params).json()
        return [c["name"] for c in r["data"]]

    assert names() == ["Alpha Foods", "zeta Labs"]  # case-insensitive
    assert names(sort="recent") == ["Alpha Foods", "zeta Labs"]
    assert names(q="software") == ["zeta Labs"]
    assert names(q="alpha.in") == ["Alpha Foods"]


def test_owner_filter(client, login):
    admin, alice = login(Role.admin), login(Role.agent)
    client.post(f"{API}/contacts", headers=admin, json={"first_name": "Mine"})
    client.post(f"{API}/contacts", headers=alice, json={"first_name": "Hers"})
    r = client.get(f"{API}/contacts", headers=admin, params={"owner_id": _me(client, alice)})
    assert [c["first_name"] for c in r.json()["data"]] == ["Hers"]


def test_todo_and_history(client, login):
    h = login(Role.agent)
    for body in (
        {"type": "task", "subject": "Send quote", "due_at": "2099-01-02T00:00:00Z"},
        {"type": "task", "subject": "Undated"},
        {"type": "note", "subject": "Likes cricket"},
        {"type": "call", "subject": "Intro call", "done": True},
    ):
        client.post(f"{API}/activities", headers=h, json=body)

    def subjects(**params):
        r = client.get(f"{API}/activities", headers=h, params=params).json()
        return [a["subject"] for a in r["data"]]

    # to-dos: soonest first, undated last; notes are never to-dos
    assert subjects(todo=True) == ["Send quote", "Undated"]
    assert subjects(todo=False, sort="recent") == ["Intro call", "Likes cricket"]
    assert subjects(todo=True, has_due=False) == ["Undated"]
    assert subjects(q="quote") == ["Send quote"]


def test_due_window_and_linked_names(client, login, stages):
    h = login(Role.agent)
    co = client.post(f"{API}/companies", headers=h, json={"name": "Acme"}).json()
    deal = client.post(
        f"{API}/deals", headers=h, json={"title": "Licence", "stage_id": stages[0]}
    ).json()
    for subject, due in (("Today", "2099-03-01T09:00:00+05:30"), ("Later", "2099-03-05T09:00:00Z")):
        body = {
            "type": "task",
            "subject": subject,
            "due_at": due,
            "deal_id": deal["id"],
            "company_id": co["id"],
        }
        client.post(f"{API}/activities", headers=h, json=body)

    # a day in India: 1 March 00:00 to 2 March 00:00 IST
    window = {"due_after": "2099-03-01T00:00:00+05:30", "due_before": "2099-03-02T00:00:00+05:30"}
    r = client.get(f"{API}/activities", headers=h, params=window).json()
    assert [a["subject"] for a in r["data"]] == ["Today"]
    a = r["data"][0]
    assert a["deal"] == {"id": deal["id"], "name": "Licence"}
    assert a["company"] == {"id": co["id"], "name": "Acme"}
    assert a["contact"] is None and a["owner"]["id"] == _me(client, h)


def test_timeline_activities_carry_linked_names(client, login, stages):
    h = login(Role.agent)
    co = client.post(f"{API}/companies", headers=h, json={"name": "Acme"}).json()
    deal = client.post(
        f"{API}/deals",
        headers=h,
        json={"title": "Licence", "stage_id": stages[0], "company_id": co["id"]},
    ).json()
    body = {"type": "task", "subject": "Call", "deal_id": deal["id"], "company_id": co["id"]}
    client.post(f"{API}/activities", headers=h, json=body)
    items = client.get(f"{API}/deals/{deal['id']}/timeline", headers=h).json()
    activity = next(i["activity"] for i in items if i["kind"] == "activity")
    assert activity["deal"]["name"] == "Licence"
    assert activity["company"]["name"] == "Acme"
