"""Deployment: settings for hosted Postgres, serving the front end, and the public demo."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import DEV_OWNER_PASSWORD, DEV_SECRET, Settings, settings
from app.main import serve_front_end
from app.models import Role
from tests.conftest import API, PASSWORD


@pytest.mark.parametrize(
    "url",
    [
        "postgres://u:p@db:5432/x",
        "postgresql://u:p@db:5432/x",
        "postgresql+psycopg://u:p@db:5432/x",
    ],
)
def test_hosted_database_urls_use_psycopg(url):
    assert Settings(DATABASE_URL=url).DATABASE_URL == "postgresql+psycopg://u:p@db:5432/x"


def test_production_needs_its_own_secrets():
    def prod(**kw):
        return Settings(_env_file=None, ENVIRONMENT="production", **kw)  # type: ignore[call-arg]

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        prod(SECRET_KEY=DEV_SECRET, FIRST_OWNER_PASSWORD="a-real-one")
    with pytest.raises(ValidationError, match="FIRST_OWNER_PASSWORD"):
        prod(SECRET_KEY="x" * 40, FIRST_OWNER_PASSWORD=DEV_OWNER_PASSWORD)
    prod(SECRET_KEY="x" * 40, FIRST_OWNER_PASSWORD="a-real-one")


def test_serves_the_front_end_without_hiding_the_api(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app-1.js").write_text("console.log(1)")
    (tmp_path / "favicon.svg").write_text("<svg/>")
    (tmp_path / "index.html").write_text("<div id=root></div>")
    app = FastAPI()

    @app.get("/api/v1/thing")
    def thing() -> dict[str, int]:
        return {"ok": 1}

    serve_front_end(app, str(tmp_path))
    c = TestClient(app)
    assert c.get("/api/v1/thing").json() == {"ok": 1}
    assert c.get("/assets/app-1.js").text == "console.log(1)"
    assert c.get("/favicon.svg").text == "<svg/>"
    for page in ("/", "/deals/12", "/account"):  # React Router pages get the app
        r = c.get(page)
        assert r.text == "<div id=root></div>"
        assert r.headers["cache-control"] == "no-cache"
    assert c.get("/api/v1/missing").status_code == 404  # not the app
    assert c.get("/../../etc/passwd").text == "<div id=root></div>"  # no escaping the folder


def test_config_outside_the_demo(client):
    assert client.get(f"{API}/config").json() == {
        "demo": False,
        "demo_password": None,
        "demo_accounts": [],
    }


@pytest.fixture
def demo(monkeypatch):
    monkeypatch.setattr(settings, "DEMO_MODE", True)


def test_demo_offers_its_accounts(client, demo):
    body = client.get(f"{API}/config").json()
    assert body["demo"] is True
    assert body["demo_password"] == "demo-password"
    assert {a["role"] for a in body["demo_accounts"]} == {"admin", "agent", "viewer"}


def test_demo_locks_what_would_break_it_for_others(client, login, demo):
    admin = login(Role.admin)
    me = client.get(f"{API}/users/me", headers=admin).json()
    blocked = [
        client.post(
            f"{API}/users/me/password",
            headers=admin,
            json={"current_password": PASSWORD, "new_password": "something-else"},
        ),
        client.post(
            f"{API}/users",
            headers=admin,
            json={"email": "new@example.com", "password": "password123", "role": "agent"},
        ),
        client.patch(f"{API}/users/{me['id']}", headers=admin, json={"full_name": "X"}),
        client.patch(f"{API}/settings/ai", headers=admin, json={"copilot_effort": "max"}),
        client.put(
            f"{API}/settings/budgets",
            headers=admin,
            json={"copilot_per_person_usd": None, "pipeline_team_usd": None},
        ),
    ]
    stage = client.get(f"{API}/pipelines", headers=admin).json()[0]["stages"][-1]
    blocked.append(client.delete(f"{API}/stages/{stage['id']}", headers=admin))
    for r in blocked:
        assert r.status_code == 403, r.text
        assert "public demo" in r.json()["detail"]
    # everything else still works
    r = client.patch(f"{API}/users/me", headers=admin, json={"full_name": "Demo visitor"})
    assert r.status_code == 200
