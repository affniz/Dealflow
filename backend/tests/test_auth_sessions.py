"""Sign-in sessions (revocable, cookie for the browser) and limits on password guessing."""

from datetime import timedelta

import jwt
from sqlmodel import col, select

from app.core.config import settings
from app.core.security import ALGORITHM
from app.models import AuthSession, LoginFailure, Role, utcnow
from tests.conftest import API, PASSWORD

CSRF = {"X-Dealflow-CSRF": "1"}


def sign_in(client, email, password=PASSWORD):  # noqa: ANN001, ANN201
    return client.post(f"{API}/login/access-token", data={"username": email, "password": password})


def me(client, headers=None):  # noqa: ANN001, ANN201
    return client.get(f"{API}/users/me", headers=headers)


def latest_session(session) -> AuthSession:  # noqa: ANN001
    return session.exec(select(AuthSession).order_by(col(AuthSession.id).desc())).first()


# ------------------------------------------------------------------ password guessing


def test_wrong_passwords_make_that_address_wait(client, login, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 3)
    login(Role.agent, "a@example.com")
    for _ in range(3):
        assert sign_in(client, "A@example.com", "wrong-password").status_code == 400
    r = sign_in(client, "a@example.com")  # even the right password has to wait
    assert r.status_code == 429
    assert "Try again in 15 minutes" in r.json()["detail"]
    assert 0 < int(r.headers["retry-after"]) <= 15 * 60
    login(Role.agent, "b@example.com")  # other accounts from the same address are fine


def test_failures_age_out_and_a_success_clears_them(client, login, session, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES", 3)
    login(Role.agent, "a@example.com")
    for _ in range(2):
        sign_in(client, "a@example.com", "wrong-password")
    assert sign_in(client, "a@example.com").status_code == 200  # clears the two
    for _ in range(2):
        sign_in(client, "a@example.com", "wrong-password")
    assert sign_in(client, "a@example.com").status_code == 200

    for _ in range(3):
        sign_in(client, "a@example.com", "wrong-password")
    assert sign_in(client, "a@example.com").status_code == 429
    for failure in session.exec(select(LoginFailure)).all():
        failure.created_at -= timedelta(minutes=settings.LOGIN_WINDOW_MINUTES)
        session.add(failure)
    session.commit()
    assert sign_in(client, "a@example.com").status_code == 200


def test_guessing_across_many_emails_is_limited_per_address(client, monkeypatch):
    monkeypatch.setattr(settings, "LOGIN_MAX_FAILURES_PER_IP", 4)
    for i in range(4):  # unknown emails count too
        assert sign_in(client, f"nobody{i}@example.com", "x").status_code == 400
    assert sign_in(client, "nobody9@example.com", "x").status_code == 429


# ------------------------------------------------------------------ ending sessions


def test_signing_out_ends_the_session(client, login):
    h = login(Role.agent)
    assert me(client, h).status_code == 200
    assert client.post(f"{API}/logout", headers=h).status_code == 200
    assert me(client, h).status_code == 401
    assert client.post(f"{API}/logout", headers=h).status_code == 200  # again: harmless


def test_a_new_password_signs_you_out_everywhere_else(client, login):
    here = login(Role.agent, "a@example.com")
    there = login(Role.agent, "a@example.com")
    r = client.post(
        f"{API}/users/me/password",
        headers=here,
        json={"current_password": PASSWORD, "new_password": "a-new-password"},
    )
    assert r.status_code == 200
    assert me(client, here).status_code == 200
    assert me(client, there).status_code == 401


def test_deactivating_or_resetting_someone_signs_them_out(client, login, session):
    admin = login(Role.admin)
    h = login(Role.agent, "a@example.com")
    uid = me(client, h).json()["id"]
    r = client.patch(f"{API}/users/{uid}", headers=admin, json={"password": "set-by-admin"})
    assert r.status_code == 200
    assert me(client, h).status_code == 401

    r = sign_in(client, "a@example.com", "set-by-admin")  # with the new password
    client.cookies.clear()
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    client.patch(f"{API}/users/{uid}", headers=admin, json={"is_active": False})
    assert me(client, h).status_code == 401
    assert session.exec(select(AuthSession).where(AuthSession.user_id == uid)).first() is None


def test_sign_out_everywhere(client, login, monkeypatch):
    one = login(Role.agent, "a@example.com")
    two = login(Role.agent, "a@example.com")
    monkeypatch.setattr(settings, "DEMO_MODE", True)  # visitors share the demo accounts
    assert client.post(f"{API}/logout/everywhere", headers=one).status_code == 403
    monkeypatch.setattr(settings, "DEMO_MODE", False)
    assert client.post(f"{API}/logout/everywhere", headers=one).status_code == 200
    assert me(client, one).status_code == 401
    assert me(client, two).status_code == 401


def test_sessions_end_when_idle_or_too_old(client, login, session):
    h = login(Role.agent)
    row = latest_session(session)
    row.last_used_at = utcnow() - timedelta(minutes=10)
    session.add(row)
    session.commit()
    assert me(client, h).status_code == 200
    session.refresh(row)
    assert utcnow() - row.last_used_at < timedelta(minutes=1)  # use keeps it going

    row.last_used_at = utcnow() - timedelta(minutes=settings.SESSION_IDLE_MINUTES + 1)
    session.add(row)
    session.commit()
    assert me(client, h).status_code == 401

    h = login(Role.agent)
    row = latest_session(session)
    row.expires_at = utcnow() - timedelta(seconds=1)
    session.add(row)
    session.commit()
    assert me(client, h).status_code == 401


def test_tokens_without_a_session_are_refused(client, login):
    uid = me(client, login(Role.agent)).json()["id"]
    old_style = jwt.encode(
        {"sub": str(uid), "exp": utcnow() + timedelta(hours=1)}, settings.SECRET_KEY, ALGORITHM
    )
    assert me(client, {"Authorization": f"Bearer {old_style}"}).status_code == 401


# ------------------------------------------------------------------ the browser's cookie


def test_the_browser_signs_in_with_an_httponly_cookie(client, login):
    login(Role.agent, "a@example.com")  # creates the person
    r = sign_in(client, "a@example.com")
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/api/v1" in cookie
    assert "secure" not in cookie  # plain http while developing; secure in production

    assert me(client).status_code == 200  # the cookie alone signs you in
    # but changing anything also needs the header another site can't add
    assert client.patch(f"{API}/users/me", json={"full_name": "X"}).status_code == 403
    r = client.patch(f"{API}/users/me", json={"full_name": "X"}, headers=CSRF)
    assert r.status_code == 200

    assert client.post(f"{API}/logout").status_code == 200
    assert me(client).status_code == 401
