"""Deleting moves records to the trash (restorable for TRASH_DAYS), and contacts and companies
keep a change history like deals do."""

from datetime import timedelta

from sqlmodel import select

from app.core.config import settings
from app.models import Activity, Deal, DealEvent, Role, utcnow
from app.services.rotting import check_rotting
from app.services.trash import purge_expired
from tests.conftest import API


def post(client, h, path, body):  # noqa: ANN001, ANN201
    r = client.post(f"{API}/{path}", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def get(client, h, path, **params):  # noqa: ANN001, ANN003, ANN201
    return client.get(f"{API}/{path}", headers=h, params=params)


def setup_records(client, h, stage_id):  # noqa: ANN001, ANN201
    company = post(client, h, "companies", {"name": "Kaveri Foods"})
    contact = post(client, h, "contacts", {"first_name": "Rohan", "company_id": company["id"]})
    deal = post(
        client,
        h,
        "deals",
        {
            "title": "Annual licence",
            "value": 5000,
            "stage_id": stage_id,
            "contact_id": contact["id"],
            "company_id": company["id"],
        },
    )
    note = post(
        client, h, "activities", {"type": "note", "subject": "Met them", "deal_id": deal["id"]}
    )
    return company, contact, deal, note


def delete(client, h, path):  # noqa: ANN001, ANN201
    return client.delete(f"{API}/{path}", headers=h)


def restore(client, h, record_type, record_id):  # noqa: ANN001, ANN201
    return client.post(f"{API}/trash/{record_type}/{record_id}/restore", headers=h)


# ------------------------------------------------------------------ soft deletes


def test_a_deleted_deal_disappears_everywhere_and_comes_back_whole(client, login, stages):
    h = login(Role.agent)
    _, contact, deal, note = setup_records(client, h, stages[0])
    did = deal["id"]
    assert delete(client, h, f"deals/{did}").status_code == 204

    assert get(client, h, f"deals/{did}").status_code == 404
    assert get(client, h, "deals").json()["count"] == 0
    board = get(client, h, f"pipelines/{deal['pipeline_id']}/board").json()
    assert all(not col["deals"] for col in board["columns"])
    assert get(client, h, f"contacts/{contact['id']}").json()["open_deal_count"] == 0
    assert get(client, h, f"activities/{note['id']}").json()["deal_id"] is None  # no link
    # can't be changed or linked to while it's gone
    assert client.patch(f"{API}/deals/{did}", headers=h, json={"title": "x"}).status_code == 404
    r = client.post(
        f"{API}/activities", headers=h, json={"type": "note", "subject": "x", "deal_id": did}
    )
    assert r.status_code == 422

    assert restore(client, h, "deal", did).status_code == 200
    assert get(client, h, f"deals/{did}").json()["contact_id"] == contact["id"]
    assert get(client, h, f"activities/{note['id']}").json()["deal_id"] == did
    kinds = [
        i["event"]["kind"] for i in get(client, h, f"deals/{did}/timeline").json() if i["event"]
    ]
    assert kinds[:2] == ["restored", "deleted"] and "created" in kinds  # history kept


def test_a_deleted_company_unlinks_until_restored(client, login, stages):
    h = login(Role.agent)
    company, contact, deal, _ = setup_records(client, h, stages[0])
    assert delete(client, h, f"companies/{company['id']}").status_code == 204
    assert get(client, h, f"contacts/{contact['id']}").json()["company_id"] is None
    assert get(client, h, f"deals/{deal['id']}").json()["company"] is None
    assert get(client, h, "companies", q="Kaveri").json()["count"] == 0
    assert get(client, h, "contacts", q="Kaveri").json()["count"] == 0  # search by company name

    restore(client, h, "company", company["id"])
    assert get(client, h, f"contacts/{contact['id']}").json()["company"]["name"] == "Kaveri Foods"


def test_who_sees_and_restores_what(client, login, stages):
    alice, bob = login(Role.agent), login(Role.agent)
    admin, viewer = login(Role.admin), login(Role.viewer)
    _, _, a_deal, _ = setup_records(client, alice, stages[0])
    b_contact = post(client, bob, "contacts", {"first_name": "Bob's person"})
    delete(client, alice, f"deals/{a_deal['id']}")
    delete(client, bob, f"contacts/{b_contact['id']}")

    mine = get(client, alice, "trash").json()
    assert [(i["type"], i["name"]) for i in mine] == [("deal", "Annual licence")]
    assert mine[0]["deleted_by"]["id"] == get(client, alice, "users/me").json()["id"]
    purge_after = mine[0]["purge_after"]
    assert purge_after > mine[0]["deleted_at"]
    assert {i["type"] for i in get(client, admin, "trash").json()} == {"deal", "contact"}

    assert restore(client, alice, "contact", b_contact["id"]).status_code == 404  # not hers
    assert restore(client, viewer, "deal", a_deal["id"]).status_code == 403
    assert restore(client, admin, "contact", b_contact["id"]).status_code == 200
    assert restore(client, admin, "contact", b_contact["id"]).status_code == 404  # not deleted


def test_deleting_for_good(client, login, stages, session):
    agent, admin = login(Role.agent), login(Role.admin)
    _, contact, deal, note = setup_records(client, agent, stages[0])
    delete(client, agent, f"contacts/{contact['id']}")
    delete(client, agent, f"deals/{deal['id']}")
    assert delete(client, agent, f"trash/deal/{deal['id']}").status_code == 403  # admins only

    assert delete(client, admin, f"trash/deal/{deal['id']}").status_code == 200
    q = select(Deal).where(Deal.id == deal["id"]).execution_options(include_deleted=True)
    assert session.exec(q).first() is None
    assert session.exec(select(DealEvent).where(DealEvent.deal_id == deal["id"])).first() is None
    assert session.get(Activity, note["id"]).deal_id is None  # the note stays, unlinked
    assert restore(client, admin, "deal", deal["id"]).status_code == 404
    assert [i["type"] for i in get(client, admin, "trash").json()] == ["contact"]


def test_the_trash_empties_itself_after_its_time(client, login, stages, session):
    h = login(Role.agent)
    _, contact, deal, _ = setup_records(client, h, stages[0])
    delete(client, h, f"deals/{deal['id']}")
    delete(client, h, f"contacts/{contact['id']}")
    soon = utcnow() + timedelta(days=settings.TRASH_DAYS - 1)
    assert purge_expired(session, now=soon) == {
        "activity": 0,
        "deal": 0,
        "contact": 0,
        "company": 0,
    }
    later = utcnow() + timedelta(days=settings.TRASH_DAYS, minutes=1)
    assert purge_expired(session, now=later) == {
        "activity": 0,
        "deal": 1,
        "contact": 1,
        "company": 0,
    }
    assert get(client, h, "trash").json() == []


def test_deleted_deals_are_left_out_of_jobs_and_block_their_stage(client, login, stages, session):
    h, admin = login(Role.agent), login(Role.admin)
    deal = post(client, h, "deals", {"title": "Old", "value": 1, "stage_id": stages[1]})
    row = session.get(Deal, deal["id"])
    row.stage_changed_at = utcnow() - timedelta(days=90)
    session.add(row)
    session.commit()
    delete(client, h, f"deals/{deal['id']}")
    assert check_rotting(session).flagged == 0  # stalled, but deleted

    r = delete(client, admin, f"stages/{stages[1]}")
    assert r.status_code == 409 and "Recently deleted" in r.json()["detail"]


# ------------------------------------------------------------------ change history


def test_contact_and_company_history(client, login):
    h = login(Role.agent)
    me = get(client, h, "users/me").json()
    company = post(client, h, "companies", {"name": "Zenith"})
    contact = post(client, h, "contacts", {"first_name": "Priya", "email": "p@zenith.in"})
    client.patch(
        f"{API}/contacts/{contact['id']}",
        headers=h,
        json={"email": "priya@zenith.in", "company_id": company["id"], "first_name": "Priya"},
    )
    client.patch(f"{API}/companies/{company['id']}", headers=h, json={"industry": "Logistics"})
    delete(client, h, f"contacts/{contact['id']}")
    restore(client, h, "contact", contact["id"])

    items = get(client, h, f"contacts/{contact['id']}/history").json()
    assert [i["kind"] for i in items] == ["restored", "deleted", "updated", "created"]
    assert items[2]["data"]["changes"] == {
        "email": ["p@zenith.in", "priya@zenith.in"],  # unchanged first name isn't listed
        "company_id": [None, company["id"]],
    }
    assert items[2]["actor"] == {"id": me["id"], "name": me["email"]}
    company_items = get(client, h, f"companies/{company['id']}/history").json()
    assert company_items[0]["data"]["changes"] == {"industry": [None, "Logistics"]}

    other = login(Role.agent)  # someone who can't see the contact can't see its history
    assert get(client, other, f"contacts/{contact['id']}/history").status_code == 404


def test_deal_updates_record_old_and_new_values(client, login, stages):
    h = login(Role.agent)
    deal = post(client, h, "deals", {"title": "Pilot", "value": 1000, "stage_id": stages[0]})
    client.patch(f"{API}/deals/{deal['id']}", headers=h, json={"value": 2500, "title": "Pilot"})
    [updated] = [
        i["event"]
        for i in get(client, h, f"deals/{deal['id']}/timeline").json()
        if i["event"] and i["event"]["kind"] == "updated"
    ]
    assert updated["data"]["fields"] == ["value"]
    assert updated["data"]["changes"] == {"value": [1000, 2500]}
