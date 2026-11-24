"""Spotting contacts that are already in the CRM before adding them again."""

import pytest

from app.models import Role
from app.services.duplicates import phone_key
from tests.conftest import API


@pytest.mark.parametrize(
    ("phone", "key"),
    [
        ("+91 98765 43210", "9876543210"),
        ("098765-43210", "9876543210"),
        ("(987) 654-3210", "9876543210"),
        ("2345678", "2345678"),  # a short landline is still a number
        ("123", None),  # too short to go on
        ("", None),
        (None, None),
    ],
)
def test_phone_numbers_compare_on_their_last_ten_digits(phone, key):
    assert phone_key(phone) == key


def _check(client, h, **body):
    r = client.post(f"{API}/contacts/duplicates", headers=h, json=body)
    assert r.status_code == 200, r.text
    return [(m["name"], m["reasons"]) for m in r.json()]


@pytest.fixture
def priya(client, login):
    alice = login(Role.agent)
    zenith = client.post(f"{API}/companies", headers=alice, json={"name": "Zenith"}).json()
    body = {
        "first_name": "Priya",
        "last_name": "Shah",
        "email": "Priya.Shah@Zenith.in",
        "phone": "+91 98765 43210",
        "company_id": zenith["id"],
    }
    contact = client.post(f"{API}/contacts", headers=alice, json=body).json()
    return {"alice": alice, "zenith": zenith, "contact": contact}


def test_matches_on_email_phone_or_name_at_the_same_company(client, login, priya):
    h, zenith = priya["alice"], priya["zenith"]["id"]
    assert _check(client, h, first_name="P", email=" priya.shah@zenith.in ") == [
        ("Priya Shah", ["email"])
    ]
    assert _check(client, h, first_name="P", phone="098765-43210") == [("Priya Shah", ["phone"])]
    assert _check(client, h, first_name="priya", last_name=" SHAH", company_id=zenith) == [
        ("Priya Shah", ["name"])
    ]
    # a name on its own is too common to call a duplicate
    assert _check(client, h, first_name="Priya", last_name="Shah") == []
    other = client.post(f"{API}/companies", headers=h, json={"name": "Kaveri"}).json()
    assert _check(client, h, first_name="Priya", last_name="Shah", company_id=other["id"]) == []

    everything = {"email": "PRIYA.SHAH@zenith.in", "phone": "9876543210", "company_id": zenith}
    assert _check(client, h, first_name="Priya", last_name="Shah", **everything) == [
        ("Priya Shah", ["email", "phone", "name"])
    ]
    # editing her isn't a duplicate of herself
    assert _check(client, h, exclude_id=priya["contact"]["id"], **everything) == []
    assert _check(client, h, first_name="Ravi", phone="123", email="") == []


def test_closest_match_first_and_whose_it_is(client, login, priya):
    bob = login(Role.agent)  # a teammate: the address book is shared
    body = {"first_name": "Reception", "phone": "+91 98765 43210"}  # same number, other person
    client.post(f"{API}/contacts", headers=bob, json=body)

    r = client.post(
        f"{API}/contacts/duplicates",
        headers=bob,
        json={"first_name": "P", "email": "priya.shah@zenith.in", "phone": "9876543210"},
    ).json()
    assert [(m["name"], m["reasons"]) for m in r] == [
        ("Priya Shah", ["email", "phone"]),
        ("Reception", ["phone"]),
    ]
    alice = client.get(f"{API}/users/me", headers=priya["alice"]).json()
    assert r[0]["owner"]["id"] == alice["id"]
    assert r[0]["company"] == {"id": priya["zenith"]["id"], "name": "Zenith"}


def test_the_trash_isnt_matched_and_viewers_cant_ask(client, login, priya):
    h = priya["alice"]
    client.delete(f"{API}/contacts/{priya['contact']['id']}", headers=h)
    assert _check(client, h, first_name="P", email="priya.shah@zenith.in") == []
    r = client.post(f"{API}/contacts/duplicates", headers=login(Role.viewer), json={})
    assert r.status_code == 403
