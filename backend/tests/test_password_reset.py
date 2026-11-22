"""Security headers, and resetting a forgotten password with a one-time link."""

from datetime import timedelta

import pytest
from sqlmodel import select

from app.api.routes import login as login_routes
from app.core.config import settings
from app.models import PasswordResetToken, Role, User
from tests.conftest import API, PASSWORD


def sign_in(client, email, password=PASSWORD):  # noqa: ANN001, ANN201
    r = client.post(f"{API}/login/access-token", data={"username": email, "password": password})
    client.cookies.clear()
    return r


# ------------------------------------------------------------------ security headers


def test_responses_carry_security_headers(client):
    h = client.get(f"{API}/config").headers
    csp = h["content-security-policy"]
    assert "script-src 'self'" in csp and "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert h["x-content-type-options"] == "nosniff"
    assert h["referrer-policy"] == "no-referrer"
    assert "strict-transport-security" not in h  # only in production, over HTTPS
    # the API docs page loads Swagger UI from a CDN, so it goes without the policy
    assert "content-security-policy" not in client.get("/docs").headers


# ------------------------------------------------------------------ by email


@pytest.fixture
def outbox(monkeypatch):
    """Emails 'sent' (SMTP set up), as (to, link)."""
    sent: list[tuple[str, str]] = []
    monkeypatch.setattr(settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(settings, "EMAILS_FROM", "dealflow@example.com")
    monkeypatch.setattr(settings, "APP_URL", "https://crm.example.com/")
    monkeypatch.setattr(login_routes, "send_reset_email", lambda to, url: sent.append((to, url)))
    return sent


def recover(client, email):  # noqa: ANN001, ANN201
    return client.post(f"{API}/login/password-recovery", json={"email": email})


def reset(client, token, new_password="a-brand-new-one"):  # noqa: ANN001, ANN201
    return client.post(
        f"{API}/login/reset-password", json={"token": token, "new_password": new_password}
    )


def test_forgotten_password_by_email(client, login, outbox):
    old_session = login(Role.agent, "a@example.com")
    r = recover(client, "A@example.com")
    assert r.status_code == 202
    [(to, url)] = outbox
    assert to == "a@example.com"
    assert url.startswith("https://crm.example.com/reset-password#dfp_")  # secret after the #
    token = url.split("#", 1)[1]

    assert reset(client, token).status_code == 200
    assert sign_in(client, "a@example.com", "a-brand-new-one").status_code == 200
    assert sign_in(client, "a@example.com").status_code == 400  # the old password is gone
    assert client.get(f"{API}/users/me", headers=old_session).status_code == 401  # signed out
    assert reset(client, token, "yet-another-one").status_code == 400  # works once


def test_recovery_reveals_nothing_and_cant_flood_an_inbox(client, login, outbox):
    login(Role.agent, "a@example.com")
    unknown = recover(client, "nobody@example.com")
    known = recover(client, "a@example.com")
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()
    assert recover(client, "a@example.com").status_code == 202  # again, moments later
    assert [to for to, _ in outbox] == ["a@example.com"]  # one email, to the real account


def test_expired_and_made_up_links_are_refused(client, login, outbox, session):
    login(Role.agent, "a@example.com")
    recover(client, "a@example.com")
    token = outbox[0][1].split("#", 1)[1]
    row = session.exec(select(PasswordResetToken)).one()
    row.expires_at -= timedelta(hours=2)
    session.add(row)
    session.commit()
    r = reset(client, token)
    assert r.status_code == 400 and "expired" in r.json()["detail"]
    assert reset(client, "dfp_made-up").status_code == 400


def test_without_email_set_up_recovery_points_to_an_admin(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    monkeypatch.setattr(settings, "SMTP_HOST", None)
    assert client.get(f"{API}/config").json()["password_reset_email"] is False
    r = recover(client, "a@example.com")
    assert r.status_code == 503 and "admin" in r.json()["detail"]


def test_no_resets_in_the_demo(client, login, monkeypatch):
    admin = login(Role.admin)
    uid = client.get(f"{API}/users/me", headers=login(Role.agent)).json()["id"]
    monkeypatch.setattr(settings, "DEMO_MODE", True)
    assert recover(client, "a@example.com").status_code == 403
    assert reset(client, "dfp_x").status_code == 403
    r = client.post(f"{API}/users/{uid}/password-reset-link", headers=admin)
    assert r.status_code == 403


# ------------------------------------------------------------------ from an admin


def test_an_admin_makes_a_reset_link(client, login, session):
    admin = login(Role.admin)
    agent = login(Role.agent, "a@example.com")
    uid = client.get(f"{API}/users/me", headers=agent).json()["id"]

    r = client.post(f"{API}/users/{uid}/password-reset-link", headers=admin)
    assert r.status_code == 200
    first = r.json()["token"]
    row = session.exec(select(PasswordResetToken)).one()
    assert timedelta(hours=23) < row.expires_at - row.created_at <= timedelta(hours=24)
    second = client.post(f"{API}/users/{uid}/password-reset-link", headers=admin).json()["token"]
    assert reset(client, first).status_code == 400  # a new link cancels the old one
    assert client.get(f"{API}/users/me", headers=agent).status_code == 200  # nothing changes yet
    assert reset(client, second).status_code == 200
    assert sign_in(client, "a@example.com", "a-brand-new-one").status_code == 200


def test_who_can_make_reset_links(client, login, session):
    admin = login(Role.admin)
    agent = login(Role.agent)
    owner = session.exec(select(User).where(User.role == Role.owner)).first()
    other = client.get(f"{API}/users/me", headers=login(Role.viewer)).json()["id"]
    assert client.post(f"{API}/users/{other}/password-reset-link", headers=agent).status_code == 403
    r = client.post(f"{API}/users/{owner.id}/password-reset-link", headers=admin)
    assert r.status_code == 403  # only an owner manages owners
    client.patch(f"{API}/users/{other}", headers=admin, json={"is_active": False})
    r = client.post(f"{API}/users/{other}/password-reset-link", headers=admin)
    assert r.status_code == 409


def test_the_reset_email(monkeypatch, caplog):
    from app.services import password_reset

    # without SMTP (developing), the link goes to the log
    password_reset.send_reset_email("a@example.com", "http://localhost:5173/reset-password#dfp_x")
    assert "reset-password#dfp_x" in caplog.text

    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):  # noqa: ANN001
            assert (host, port) == ("smtp.example.com", 587)

        def starttls(self, context):  # noqa: ANN001
            sent.append("tls")

        def login(self, user, password):  # noqa: ANN001
            sent.append(("login", user))

        def send_message(self, msg):  # noqa: ANN001
            sent.append(msg)

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *exc):  # noqa: ANN002, ANN204
            return False

    monkeypatch.setattr(password_reset.smtplib, "SMTP", FakeSMTP)
    for key, value in {
        "SMTP_HOST": "smtp.example.com",
        "SMTP_USER": "mailer",
        "EMAILS_FROM": "Dealflow <dealflow@example.com>",
        "APP_URL": "https://crm.example.com",
    }.items():
        monkeypatch.setattr(settings, key, value)
    password_reset.send_reset_email("a@example.com", "https://crm.example.com/reset-password#t")
    tls, login, msg = sent
    assert tls == "tls" and login == ("login", "mailer")
    assert msg["To"] == "a@example.com" and "reset-password#t" in msg.get_content()
