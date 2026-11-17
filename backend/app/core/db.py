from collections.abc import Iterator

from sqlmodel import Session, create_engine

from app.core.config import settings

_connect_args = {"check_same_thread": False} if settings.DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(settings.DATABASE_URL, connect_args=_connect_args)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
