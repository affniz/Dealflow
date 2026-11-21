"""Approving a proposal twice at the same moment applies it once.

This needs two real database sessions in two threads, so unlike the other tests it commits its
own rows (and deletes them afterwards) instead of running in a rolled-back transaction.
"""

import threading
import time
import uuid

import pytest
from fastapi import HTTPException
from sqlalchemy import Engine
from sqlmodel import Session, col, delete, select

from app.agent import proposals
from app.models import (
    Activity,
    AgentProposal,
    Deal,
    DealEvent,
    Pipeline,
    ProposalStatus,
    Role,
    Stage,
    User,
)


@pytest.fixture
def committed_proposal(engine: Engine):  # noqa: ANN201
    tag = uuid.uuid4().hex[:8]
    with Session(engine) as s:
        user = User(email=f"race-{tag}@example.com", role=Role.agent, hashed_password="x")
        pipeline = Pipeline(name=f"Race {tag}")
        s.add_all([user, pipeline])
        s.flush()
        stage = Stage(name="Lead", pipeline_id=pipeline.id)  # type: ignore[arg-type]
        s.add(stage)
        s.flush()
        deal = Deal(title="Race", stage_id=stage.id, pipeline_id=pipeline.id, owner_id=user.id)  # type: ignore[arg-type]
        s.add(deal)
        s.flush()
        proposal = AgentProposal(
            source="copilot",
            user_id=user.id,  # type: ignore[arg-type]
            deal_id=deal.id,
            action="log_activity",
            params={
                "type": "note",
                "subject": "Called them",
                "body": None,
                "due_at": None,
                "done": True,
                "deal_id": deal.id,
                "contact_id": None,
                "company_id": None,
            },
            summary="Log a note",
        )
        s.add(proposal)
        s.commit()
        ids = {"user": user.id, "pipeline": pipeline.id, "deal": deal.id, "proposal": proposal.id}
    yield ids
    with Session(engine) as s:
        s.exec(delete(Activity).where(col(Activity.owner_id) == ids["user"]))
        s.exec(delete(AgentProposal).where(col(AgentProposal.id) == ids["proposal"]))
        s.exec(delete(DealEvent).where(col(DealEvent.deal_id) == ids["deal"]))
        s.exec(delete(Deal).where(col(Deal.id) == ids["deal"]))
        s.exec(delete(Stage).where(col(Stage.pipeline_id) == ids["pipeline"]))
        s.exec(delete(Pipeline).where(col(Pipeline.id) == ids["pipeline"]))
        s.exec(delete(User).where(col(User.id) == ids["user"]))
        s.commit()


def test_two_simultaneous_approvals_apply_the_change_once(engine, committed_proposal, monkeypatch):
    ids = committed_proposal
    applying = threading.Event()
    real_apply = proposals._apply

    def slow_apply(session, p, user):  # noqa: ANN001, ANN202
        # the first approval is mid-change when the second one arrives
        applying.set()
        time.sleep(0.5)
        real_apply(session, p, user)

    monkeypatch.setattr(proposals, "_apply", slow_apply)
    outcomes: list[object] = []

    def approve() -> None:
        with Session(engine) as s:
            user = s.get(User, ids["user"])
            try:
                outcomes.append(proposals.decide(s, user, ids["proposal"], approve=True).status)  # type: ignore[arg-type]
            except HTTPException as exc:
                outcomes.append(exc.status_code)

    first = threading.Thread(target=approve)
    first.start()
    assert applying.wait(5)
    second = threading.Thread(target=approve)
    second.start()
    first.join(10)
    second.join(10)

    assert sorted(map(str, outcomes)) == ["409", ProposalStatus.approved.value]
    with Session(engine) as s:
        notes = s.exec(select(Activity).where(Activity.owner_id == ids["user"])).all()
        assert len(notes) == 1
