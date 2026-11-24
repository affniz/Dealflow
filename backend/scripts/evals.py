"""Grade the AI agents on realistic CRM situations (backend/evals), against the real Claude API.

    uv run python scripts/evals.py --list                  # the scenarios
    uv run python scripts/evals.py                         # all of them, once, with the app's
                                                           # default models and effort
    uv run python scripts/evals.py --repeat 3 --judge      # 3 runs each, plus a judged score
    uv run python scripts/evals.py --model claude-haiku-5-5 --effort low --agent pipeline
    uv run python scripts/evals.py --baseline evals/results/<earlier>.json

It runs in its own database (your DATABASE_URL, renamed dealflow_evals; EVAL_DATABASE_URL
overrides it), which it creates and empties on every run, and each scenario's records are rolled
back when it finishes. Results go to evals/results/ (not committed). Credentials:
ANTHROPIC_API_KEY in backend/.env, or your `ant auth login` profile.
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, make_url, text  # noqa: E402
from sqlmodel import Session, SQLModel  # noqa: E402

from app.agent import copilot, pipeline  # noqa: E402
from app.core.config import settings  # noqa: E402
from evals import report  # noqa: E402
from evals.harness import RunResult  # noqa: E402
from evals.judge import DEFAULT_JUDGE_MODEL, make_judge  # noqa: E402
from evals.scenarios import SCENARIOS  # noqa: E402

# a rough guide for the "continue?" question, from runs with the default models
TYPICAL_COST_USD = {"pipeline": 0.02, "copilot": 0.02, "judge": 0.01}


def eval_url() -> str:
    url = os.environ.get("EVAL_DATABASE_URL") or make_url(settings.DATABASE_URL).set(
        database="dealflow_evals"
    ).render_as_string(False)
    if "eval" not in (make_url(url).database or ""):
        sys.exit(f"Refusing to use {make_url(url).database!r}: its name must contain 'eval'")
    return url


def fresh_database(url: str):  # noqa: ANN201
    """Create the evals database if needed and give it an empty schema with the defaults."""
    from app.initial_data import init_db

    parsed = make_url(url)
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        found = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": parsed.database}
        ).first()
        if not found:
            conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    admin.dispose()
    engine = create_engine(url)
    SQLModel.metadata.drop_all(engine)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        init_db(session)  # the owner, the default pipeline and lost reasons
    return engine


def git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
        dirty = subprocess.run(["git", "diff", "--quiet"], cwd=ROOT).returncode != 0
        return out.stdout.strip() + ("+changes" if dirty else "") if out.returncode == 0 else None
    except OSError:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--list", action="store_true", help="list the scenarios and exit")
    parser.add_argument("--agent", choices=["pipeline", "copilot"], help="only this agent")
    parser.add_argument(
        "--scenario", action="append", default=[], help="only scenarios whose id contains this"
    )
    parser.add_argument("--model", help="model for both agents (default: the app's settings)")
    parser.add_argument("--effort", help="effort for both agents (default: the app's settings)")
    parser.add_argument("--repeat", type=int, default=1, help="runs per scenario (default 1)")
    parser.add_argument("--judge", action="store_true", help="also get a model-graded score")
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--baseline", type=Path, help="an earlier results file to compare with")
    parser.add_argument("--yes", action="store_true", help="don't ask before spending")
    parser.add_argument("--verbose", "-v", action="store_true", help="print each note or reply")
    args = parser.parse_args()

    chosen = [
        s
        for s in SCENARIOS
        if (not args.agent or s.agent == args.agent)
        and (not args.scenario or any(part in s.id for part in args.scenario))
    ]
    if args.list or not chosen:
        for s in chosen or SCENARIOS:
            print(f"{s.id:<38} {s.title}")
        sys.exit(0 if chosen else "No scenario matches.")

    client = copilot.get_client()
    if client is None:
        sys.exit(
            "No Claude credentials: set ANTHROPIC_API_KEY in backend/.env or run `ant auth login`."
        )
    models = {
        "pipeline": (
            args.model or settings.PIPELINE_MODEL,
            args.effort or settings.PIPELINE_EFFORT,
        ),
        "copilot": (args.model or settings.COPILOT_MODEL, args.effort or settings.COPILOT_EFFORT),
    }
    runs = len(chosen) * args.repeat
    estimate = sum(TYPICAL_COST_USD[s.agent] for s in chosen) * args.repeat
    if args.judge:
        estimate += TYPICAL_COST_USD["judge"] * runs
    plan = ", ".join(
        f"{agent} {m} ({e})"
        for agent, (m, e) in models.items()
        if any(s.agent == agent for s in chosen)
    )
    print(f"{runs} runs of {len(chosen)} scenarios: {plan}" + (" + judge" if args.judge else ""))
    if not args.yes:
        answer = input(f"This makes real API calls, roughly ${estimate:.2f}. Continue? [y/N] ")
        if answer.strip().lower() != "y":
            sys.exit("Cancelled.")

    url = eval_url()
    engine = fresh_database(url)
    judge = make_judge(client, args.judge_model) if args.judge else None

    from evals.harness import run_scenario

    results: list[RunResult] = []
    for scenario in chosen:
        model, effort = models[scenario.agent]
        for i in range(args.repeat):
            with engine.connect() as connection:
                r = run_scenario(scenario, connection, client, model, effort, judge)
            results.append(r)
            mark = "pass" if r.passed else "FAIL"
            passed = sum(c.passed for c in r.checks)
            judged = f"  judge {r.judge_score}/5" if r.judge_score is not None else ""
            print(
                f"{mark}  {scenario.id}#{i + 1}  checks {passed}/{len(r.checks)}{judged}  "
                f"${r.outcome.cost_usd:.4f}  {r.outcome.seconds:.0f}s"
            )
            if r.outcome.error:
                print(f"      error: {r.outcome.error}")
            for c in r.checks:
                if not c.passed:
                    print(f"      ✗ {c.name}: {c.detail}")
            if args.verbose or not r.passed:
                for p in r.outcome.proposals:
                    print(f"      proposed: {p.summary}")
                print("      " + (r.outcome.text or "(no text)").replace("\n", "\n      "))
            if r.judge_reasons and (args.verbose or (r.judge_score or 5) <= 3):
                print(f"      judge: {r.judge_reasons}")

    summary = report.summarize(results)
    baseline = None
    if args.baseline:
        import json

        baseline = json.loads(args.baseline.read_text())
    print()
    print(report.table(summary, baseline))
    if failed := report.failures(summary):
        print("\nFailed checks:\n" + failed)
    meta = {
        "at": datetime.now().isoformat(timespec="seconds"),
        "commit": git_commit(),
        "models": {agent: {"model": m, "effort": e} for agent, (m, e) in models.items()},
        "judge_model": args.judge_model if args.judge else None,
        "repeat": args.repeat,
        # which prompts were graded, so a result can be tied to a prompt change
        "prompts": {
            "copilot_version": copilot.CURRENT_PROMPT,
            "pipeline_sha256": sha256(pipeline.SYSTEM_PROMPT.encode()).hexdigest()[:12],
        },
    }
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    name = f"{stamp}_{(args.model or 'default').replace('/', '-')}.json"
    path = report.save(results, summary, meta, report.RESULTS_DIR / name)
    print(f"\nSaved {path.relative_to(ROOT)}")
    engine.dispose()


if __name__ == "__main__":
    main()
