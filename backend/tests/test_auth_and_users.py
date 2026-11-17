from app.core.config import settings
from app.models import Role
from tests.conftest import API


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_seeded_owner_can_log_in(client):
    r = client.post(
        f"{API}/login/access-token",
        data={"username": settings.FIRST_OWNER_EMAIL, "password": settings.FIRST_OWNER_PASSWORD},
    )
    assert r.status_code == 200
    me = client.get(
        f"{API}/users/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}
    )
    assert me.json()["role"] == "owner"


def test_bad_password_and_bad_token(client):
    r = client.post(
        f"{API}/login/access-token",
        data={"username": settings.FIRST_OWNER_EMAIL, "password": "wrong-password"},
    )
    assert r.status_code == 400
    assert (
        client.get(f"{API}/users/me", headers={"Authorization": "Bearer junk"}).status_code == 401
    )
    assert client.get(f"{API}/users/me").status_code == 401


def test_admin_manages_users_but_not_owners(client, login):
    admin = login(Role.admin)
    r = client.post(
        f"{API}/users",
        headers=admin,
        json={"email": "Rep@Example.com", "password": "password123", "role": "agent"},
    )
    assert r.status_code == 201
    assert r.json()["email"] == "rep@example.com"
    dup = {"email": "rep@example.com", "password": "password123"}
    assert client.post(f"{API}/users", headers=admin, json=dup).status_code == 409
    owner_body = {"email": "boss@example.com", "password": "password123", "role": "owner"}
    assert client.post(f"{API}/users", headers=admin, json=owner_body).status_code == 403


def test_agents_cannot_list_users(client, login):
    assert client.get(f"{API}/users", headers=login(Role.agent)).status_code == 403


def test_cannot_demote_self(client, login):
    admin = login(Role.admin)
    me = client.get(f"{API}/users/me", headers=admin).json()
    r = client.patch(f"{API}/users/{me['id']}", headers=admin, json={"role": "agent"})
    assert r.status_code == 400


def test_change_password(client, login):
    h = login(Role.agent)
    bad = {"current_password": "nope-nope", "new_password": "newpassword1"}
    assert client.post(f"{API}/users/me/password", headers=h, json=bad).status_code == 400
    ok = {"current_password": "password123", "new_password": "newpassword1"}
    assert client.post(f"{API}/users/me/password", headers=h, json=ok).status_code == 200
