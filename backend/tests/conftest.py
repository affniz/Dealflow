from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.config import settings
from app.core.db import get_session
from app.core.security import hash_password
from app.initial_data import init_db
from app.main import app
from app.models import Pipeline, Role, User

API = settings.API_V1_STR
PASSWORD = "password123"


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        init_db(s)
        yield s


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
        return {"Authorization": f"Bearer {r.json()['access_token']}"}

    return _login


@pytest.fixture
def stages(session: Session) -> list[int]:
    """Default Sales stage ids: Lead 10%, Qualified 25%, Proposal 50%, Negotiation 75%."""
    pipeline = session.exec(select(Pipeline)).one()
    return [s.id for s in pipeline.stages]  # type: ignore[misc]
