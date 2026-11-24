"""Searches match what was typed: `%`, `_` and `\\` are plain characters, not wildcards."""

import pytest

from app.models import Role
from app.services.search import escape_like
from tests.conftest import API
from tests.test_mcp import _call, _token


@pytest.mark.parametrize(
    ("text", "escaped"),
    [
        ("50%", "50\\%"),
        ("q3_report", "q3\\_report"),
        ("C:\\deals", "C:\\\\deals"),
        ("\\%", "\\\\\\%"),
        ("plain", "plain"),
    ],
)
def test_wildcards_are_escaped(text, escaped):
    assert escape_like(text) == escaped


def _list(client, h, kind, q, field):
    r = client.get(f"{API}/{kind}", headers=h, params={"q": q})
    assert r.status_code == 200, r.text
    return sorted(row[field] for row in r.json()["data"])


def test_deal_search_takes_wildcards_literally(client, login, stages):
    h = login(Role.agent)
    for title in ("50% upfront", "500 seats", "q3_report", "q3 report", "C:\\deals"):
        client.post(f"{API}/deals", headers=h, json={"title": title, "stage_id": stages[0]})

    def titles(q):
        return _list(client, h, "deals", q, "title")

    assert titles("50%") == ["50% upfront"]  # not "500 seats"
    assert titles("q3_") == ["q3_report"]  # not "q3 report"
    assert titles("\\") == ["C:\\deals"]
    assert titles("%") == ["50% upfront"]  # not every deal
    assert titles("_") == ["q3_report"]
    assert titles("50") == ["50% upfront", "500 seats"]  # plain searches still work


def test_address_book_and_activity_searches_too(client, login):
    h = login(Role.agent)
    for first, email in (("Priya", "priya_s@zenith.in"), ("Ravi", "ravis@zenith.in")):
        client.post(f"{API}/contacts", headers=h, json={"first_name": first, "email": email})
    for name in ("100% Organic", "1000 Cranes"):
        client.post(f"{API}/companies", headers=h, json={"name": name})
    for subject in ("Discount: 10% off", "Called 100 times"):
        client.post(f"{API}/activities", headers=h, json={"type": "note", "subject": subject})

    assert _list(client, h, "contacts", "_s@", "first_name") == ["Priya"]
    assert _list(client, h, "contacts", "%", "first_name") == []
    assert _list(client, h, "companies", "100%", "name") == ["100% Organic"]
    assert _list(client, h, "activities", "10%", "subject") == ["Discount: 10% off"]
    # surrounding spaces are ignored, as before
    assert _list(client, h, "companies", " cranes ", "name") == ["1000 Cranes"]


def test_copilot_searches_take_wildcards_literally(client, login, stages):
    h = login(Role.agent)
    token = _token(client, h)
    for title in ("50% upfront", "500 seats"):
        client.post(f"{API}/deals", headers=h, json={"title": title, "stage_id": stages[0]})
    zenith = client.post(f"{API}/companies", headers=h, json={"name": "Zenith"}).json()
    body = {"first_name": "Priya", "last_name": "Shah", "company_id": zenith["id"]}
    client.post(f"{API}/contacts", headers=h, json=body)
    client.post(f"{API}/contacts", headers=h, json={"first_name": "Ravi"})

    args = {"status": "any", "stalled_only": False, "mine_only": False, "limit": 50}
    error, found = _call(client, token, "search_deals", query="50%", **args)
    assert not error
    assert [d["title"] for d in found["deals"]] == ["50% upfront"]

    def contacts(query):
        error, found = _call(client, token, "search_contacts", query=query)
        assert not error
        return [c["name"] for c in found["contacts"]]

    assert contacts("%") == []
    # the full name finds them, as it does on the Contacts page
    assert contacts("priya shah") == ["Priya Shah"]
    assert contacts("zenith") == ["Priya Shah"]
