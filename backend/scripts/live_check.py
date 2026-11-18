"""Try the AI agents against the real Claude API and print what each question cost.

Runs a few typical Copilot questions as a demo agent and one pipeline review, then prints the
answers, the proposals made and the usage per question and model. It writes conversations,
proposals and usage rows to the database, so point it at a demo database:

    uv run python -m app.initial_data && uv run python -m app.demo_data   # fresh demo DB
    uv run python scripts/live_check.py                       # models from the app's settings
    uv run python scripts/live_check.py --model claude-sonnet-5-5

Credentials: ANTHROPIC_API_KEY in backend/.env, or your `ant auth login` profile.
"""

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session, col, func, select  # noqa: E402

from app.agent import copilot  # noqa: E402
from app.agent.pipeline import review_stalled_deals  # noqa: E402
from app.core.db import engine  # noqa: E402
from app.models import AgentConversation, AgentProposal, AIUsage, User  # noqa: E402
from app.services.ai_settings import get_ai_settings  # noqa: E402

QUESTIONS = [
    "What needs my attention today?",
    "Which of my deals are stalled, and what should I do about each?",
    "Log a call with Priya on Fleet tracking rollout: she wants a revised quote by Friday.",
]


def usage_for(session: Session, turn_ids: list[str]) -> list[AIUsage]:
    return list(session.exec(select(AIUsage).where(col(AIUsage.turn_id).in_(turn_ids))).all())


def print_usage(rows: list[AIUsage]) -> Decimal:
    total = Decimal(0)
    for r in rows:
        cost = r.cost_usd or Decimal(0)
        total += cost
        print(
            f"    {r.model:<20} in {r.input_tokens:>6}  cache-read {r.cache_read_tokens:>6}  "
            f"cache-write {r.cache_write_tokens:>6}  out {r.output_tokens:>5}  ${cost:.4f}"
        )
    print(f"    = ${total:.4f} over {len(rows)} calls")
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--model", help="use this model for both agents")
    parser.add_argument("--effort", help="use this effort for both agents")
    parser.add_argument("--user", default="arjun@dealflow.dev", help="demo user to ask as")
    parser.add_argument("--skip-review", action="store_true", help="only run the Copilot")
    parser.add_argument("--yes", action="store_true", help="don't ask before spending")
    args = parser.parse_args()

    client = copilot.get_client()
    if client is None:
        sys.exit(
            "No Claude credentials: set ANTHROPIC_API_KEY in backend/.env or run `ant auth login`."
        )
    with Session(engine) as session:
        ai = get_ai_settings(session)
    copilot_model = args.model or ai.copilot_model
    copilot_effort = args.effort or ai.copilot_effort
    pipeline_model = args.model or ai.pipeline_model
    pipeline_effort = args.effort or ai.pipeline_effort
    plan = (
        f"Copilot {copilot_model} ({copilot_effort}), "
        f"pipeline agent {pipeline_model} ({pipeline_effort})"
    )
    if not args.yes:
        answer = input(
            f"This makes real API calls: {plan}; usually well under $1 in total. Continue? [y/N] "
        )
        if answer.strip().lower() != "y":
            sys.exit("Cancelled.")

    grand = Decimal(0)
    with Session(engine) as session:
        user = session.exec(select(User).where(User.email == args.user)).first()
        if user is None:
            sys.exit(f"No user {args.user}; load the demo data first (python -m app.demo_data).")
        # the chosen model is set on the conversation; the app's own settings aren't touched
        conv = AgentConversation(
            user_id=user.id,  # type: ignore[arg-type]
            title="Live check",
            model=copilot_model,
            effort=copilot_effort,
        )
        session.add(conv)
        session.commit()
        session.refresh(conv)

        for question in QUESTIONS:
            print(f"\n=== Copilot ({user.full_name}): {question}")
            before = {r.turn_id for r in session.exec(select(AIUsage)).all()}
            seen = set(session.exec(select(AgentProposal.id)).all())
            copilot.run_turn(session, client, user, conv, question)
            session.refresh(conv)
            last = conv.messages[-1]
            text = (
                last["content"]
                if isinstance(last["content"], str)
                else "\n".join(
                    b.get("text", "") for b in last["content"] if b.get("type") == "text"
                )
            )
            print(text.strip() or "(no text)")
            for p in session.exec(
                select(AgentProposal).where(AgentProposal.conversation_id == conv.id)
            ).all():
                if p.id in seen:
                    continue
                print(f"  proposal #{p.id} [{p.status}]: {p.summary}")
            turns = {r.turn_id for r in session.exec(select(AIUsage)).all()} - before
            grand += print_usage(usage_for(session, list(turns)))

        if not args.skip_review:
            print("\n=== Pipeline review of stalled deals")
            before = session.exec(select(func.max(AIUsage.id))).one() or 0
            summary = review_stalled_deals(session, client, pipeline_model, pipeline_effort)
            print(f"  {summary}")
            rows = session.exec(select(AIUsage).where(col(AIUsage.id) > before)).all()
            grand += print_usage(list(rows))

    print(f"\nTotal: ${grand:.4f} ({plan})")


if __name__ == "__main__":
    main()
