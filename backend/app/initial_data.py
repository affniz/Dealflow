"""Create the first owner account, a default sales pipeline and lost reasons.

Safe to run repeatedly: it only adds what's missing.
Usage: python -m app.initial_data
"""

from sqlmodel import Session, select

from app.core.config import settings
from app.core.db import engine
from app.core.security import hash_password
from app.models import LostReason, Pipeline, Role, Stage, User

DEFAULT_STAGES = [("Lead", 10), ("Qualified", 25), ("Proposal", 50), ("Negotiation", 75)]
DEFAULT_LOST_REASONS = ["Price", "Chose a competitor", "No budget", "No response", "Bad timing"]


def init_db(session: Session) -> None:
    if session.exec(select(User).where(User.role == Role.owner)).first() is None:
        session.add(
            User(
                email=settings.FIRST_OWNER_EMAIL.lower(),
                full_name="Owner",
                role=Role.owner,
                hashed_password=hash_password(settings.FIRST_OWNER_PASSWORD),
            )
        )
    if session.exec(select(Pipeline)).first() is None:
        pipeline = Pipeline(name="Sales")
        pipeline.stages = [
            Stage(name=name, position=i, probability=p)
            for i, (name, p) in enumerate(DEFAULT_STAGES)
        ]
        session.add(pipeline)
    if session.exec(select(LostReason)).first() is None:
        session.add_all(LostReason(label=label) for label in DEFAULT_LOST_REASONS)
    session.commit()


if __name__ == "__main__":
    with Session(engine) as s:
        init_db(s)
    print("Initial data ready")
