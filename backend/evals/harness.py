"""Running one scenario: build its world, let the agent act, record what it did, grade it.

Every run happens inside a database transaction that is rolled back afterwards (commits inside
the agents only release savepoints), so runs are independent and leave nothing behind.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import Connection
from sqlmodel import Session, col, select

from app.agent import copilot
from app.agent.loop import MessagesClient
from app.agent.pipeline import review_deal
from app.models import AgentConversation, AgentProposal, AIUsage, RunStatus
from evals.world import Builder, World

Agent = Literal["pipeline", "copilot"]


@dataclass
class Proposal:
    action: str
    params: dict[str, Any]
    summary: str
    rationale: str | None
    deal_id: int | None


@dataclass
class Outcome:
    """What the agent did in one run."""

    text: str = ""  # the pipeline agent's note to the owner, or the Copilot's reply
    proposals: list[Proposal] = field(default_factory=list)
    tool_calls: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # in order
    error: str | None = None
    calls: int = 0  # model calls
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    seconds: float = 0.0


@dataclass
class Check:
    """One thing a good answer does. `test` returns None when it holds, or what went wrong."""

    name: str
    test: Callable[[World, Outcome], str | None]


@dataclass
class Scenario:
    id: str
    agent: Agent
    title: str
    build: Callable[[Builder], World]
    checks: list[Check]
    # the pipeline agent reviews this deal; the Copilot is asked `ask` as `as_user`
    deal: str | None = None
    ask: str | None = None
    as_user: str | None = None
    # what a good note or answer looks like, for the model judge (evals.judge)
    rubric: str = ""


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str | None = None


@dataclass
class RunResult:
    scenario: str
    agent: Agent
    outcome: Outcome
    checks: list[CheckResult]
    judge_score: int | None = None
    judge_reasons: str | None = None
    judge_cost_usd: Decimal = Decimal(0)

    @property
    def passed(self) -> bool:
        return self.outcome.error is None and all(c.passed for c in self.checks)


def _tool_calls(messages: list[dict[str, Any]]) -> list[tuple[str, dict[str, Any]]]:
    calls = []
    for m in messages:
        if m["role"] == "assistant" and isinstance(m["content"], list):
            calls += [(b["name"], b["input"]) for b in m["content"] if b.get("type") == "tool_use"]
    return calls


def _last_text(messages: list[dict[str, Any]]) -> str:
    for m in reversed(messages):
        if m["role"] != "assistant":
            continue
        if isinstance(m["content"], str):
            return m["content"]
        return "\n".join(b.get("text", "") for b in m["content"] if b.get("type") == "text")
    return ""


def _proposals(session: Session, **where: int) -> list[Proposal]:
    stmt = select(AgentProposal).order_by(col(AgentProposal.id))
    for name, value in where.items():
        stmt = stmt.where(getattr(AgentProposal, name) == value)
    return [
        Proposal(p.action, p.params, p.summary, p.rationale, p.deal_id)
        for p in session.exec(stmt).all()
    ]


def _usage(session: Session, outcome: Outcome, **where: int) -> None:
    stmt = select(AIUsage)
    for name, value in where.items():
        stmt = stmt.where(getattr(AIUsage, name) == value)
    for row in session.exec(stmt).all():
        outcome.calls += 1
        outcome.input_tokens += row.input_tokens + row.cache_read_tokens + row.cache_write_tokens
        outcome.output_tokens += row.output_tokens
        outcome.cost_usd += row.cost_usd or Decimal(0)


def act(
    scenario: Scenario,
    world: World,
    client: MessagesClient,
    model: str,
    effort: str,
) -> Outcome:
    session = world.session
    outcome = Outcome()
    started = time.monotonic()
    if scenario.agent == "pipeline":
        assert scenario.deal is not None
        run = review_deal(session, client, world.deals[scenario.deal], model, effort)
        if run.status == RunStatus.failed:
            outcome.error = run.error or "The review failed"
        outcome.text = run.summary or ""
        outcome.tool_calls = _tool_calls(run.messages)
        outcome.proposals = _proposals(session, run_id=run.id)  # type: ignore[arg-type]
        _usage(session, outcome, run_id=run.id)  # type: ignore[arg-type]
    else:
        assert scenario.ask is not None and scenario.as_user is not None
        user = world.users[scenario.as_user]
        conv = AgentConversation(user_id=user.id, title="Eval", model=model, effort=effort)  # type: ignore[arg-type]
        session.add(conv)
        session.commit()
        try:
            copilot.run_turn(session, client, user, conv, scenario.ask)
        except Exception as exc:  # an API error, or the budget: the run counts as failed
            session.rollback()
            outcome.error = f"{type(exc).__name__}: {exc}"
        else:
            outcome.text = _last_text(conv.messages)
            outcome.tool_calls = _tool_calls(conv.messages)
        outcome.proposals = _proposals(session, conversation_id=conv.id)  # type: ignore[arg-type]
        _usage(session, outcome, conversation_id=conv.id)  # type: ignore[arg-type]
    outcome.seconds = time.monotonic() - started
    return outcome


def grade(scenario: Scenario, world: World, outcome: Outcome) -> list[CheckResult]:
    results = []
    for check in scenario.checks:
        try:
            problem = check.test(world, outcome)
        except Exception as exc:  # a check that crashes on odd output counts as failed
            problem = f"check crashed: {type(exc).__name__}: {exc}"
        results.append(CheckResult(check.name, problem is None, problem))
    return results


def run_scenario(
    scenario: Scenario,
    connection: Connection,
    client: MessagesClient,
    model: str,
    effort: str,
    judge: Callable[[Scenario, World, Outcome], tuple[int, str, Decimal]] | None = None,
) -> RunResult:
    """One run of one scenario, in a transaction on `connection` that's rolled back after
    (a savepoint, when the connection is already in a transaction, as in the tests)."""
    outer = connection.begin_nested() if connection.in_transaction() else connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        world = scenario.build(Builder(session))
        outcome = act(scenario, world, client, model, effort)
        result = RunResult(scenario.id, scenario.agent, outcome, grade(scenario, world, outcome))
        if judge is not None and outcome.error is None:
            score, reasons, cost = judge(scenario, world, outcome)
            result.judge_score, result.judge_reasons, result.judge_cost_usd = score, reasons, cost
        return result
    finally:
        session.close()
        outer.rollback()
