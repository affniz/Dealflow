from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, make_url
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.core.db import get_session
from app.core.security import hash_password
from app.initial_data import init_db
from app.main import app
from app.models import Pipeline, Role, User

API = settings.API_V1_STR
PASSWORD = "password123"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    url = settings.TEST_DATABASE_URL
    # the schema is dropped and recreated here, so refuse anything that looks like real data
    if url == settings.DATABASE_URL or "test" not in make_url(url).database:
        raise RuntimeError(f"TEST_DATABASE_URL must be a separate *test* database, got {url}")
    eng = create_engine(url)
    SQLModel.metadata.drop_all(eng)
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """Each test runs in a transaction that is rolled back at the end.

    Route handlers call session.commit(); with create_savepoint those commits only
    release a savepoint, so nothing leaks between tests.
    """
    connection = engine.connect()
    outer = connection.begin()
    s = Session(bind=connection, join_transaction_mode="create_savepoint")
    init_db(s)
    try:
        yield s
    finally:
        s.close()
        outer.rollback()
        connection.close()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def login(client: TestClient, session: Session) -> Callable[..., dict[str, str]]:
    """login(role) -> auth headers for a fresh user with that role."""
    counter = iter(range(1000))

    def _login(role: Role = Role.agent, email: str | None = None) -> dict[str, str]:
        email = email or f"{role.value}{next(counter)}@example.com"
        if session.exec(select(User).where(User.email == email)).first() is None:
            session.add(User(email=email, role=role, hashed_password=hash_password(PASSWORD)))
            session.commit()
        r = client.post(f"{API}/login/access-token", data={"username": email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        # tests sign in as several people on one client: use the bearer token, not the cookie
        client.cookies.clear()
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


@pytest.fixture
def stages(session: Session) -> list[int]:
    """Default Sales stage ids: Lead 10%, Qualified 25%, Proposal 50%, Negotiation 75%."""
    pipeline = session.exec(select(Pipeline)).one()
    return [s.id for s in pipeline.stages]  # type: ignore[misc]
