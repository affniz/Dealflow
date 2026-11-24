"""Summing up eval runs: a table to read, and a JSON file to compare later runs against."""

import json
from collections import defaultdict
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path
from statistics import mean
from typing import Any

from evals.harness import RunResult

RESULTS_DIR = Path(__file__).parent / "results"


def summarize(results: list[RunResult]) -> dict[str, Any]:
    by_scenario: dict[str, list[RunResult]] = defaultdict(list)
    for r in results:
        by_scenario[r.scenario].append(r)
    scenarios = {}
    for sid, runs in by_scenario.items():
        judged = [r.judge_score for r in runs if r.judge_score is not None]
        checks = [c for r in runs for c in r.checks]
        failures: dict[str, int] = defaultdict(int)
        for r in runs:
            if r.outcome.error:
                failures[f"error: {r.outcome.error[:80]}"] += 1
            for c in r.checks:
                if not c.passed:
                    failures[c.name] += 1
        scenarios[sid] = {
            "agent": runs[0].agent,
            "runs": len(runs),
            "pass_rate": sum(r.passed for r in runs) / len(runs),
            "check_pass_rate": sum(c.passed for c in checks) / len(checks) if checks else 1.0,
            "judge": mean(judged) if judged else None,
            "cost_usd": float(sum(r.outcome.cost_usd for r in runs) / len(runs)),
            "seconds": mean(r.outcome.seconds for r in runs),
            "failures": dict(failures),
        }
    all_checks = [c for r in results for c in r.checks]
    judged = [r.judge_score for r in results if r.judge_score is not None]
    return {
        "scenarios": scenarios,
        "overall": {
            "runs": len(results),
            "pass_rate": sum(r.passed for r in results) / len(results) if results else 0,
            "check_pass_rate": (
                sum(c.passed for c in all_checks) / len(all_checks) if all_checks else 0
            ),
            "judge": mean(judged) if judged else None,
            "agent_cost_usd": float(sum(r.outcome.cost_usd for r in results)),
            "judge_cost_usd": float(sum(r.judge_cost_usd for r in results)),
        },
    }


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _judge(x: float | None) -> str:
    return "-" if x is None else f"{x:.1f}"


def _delta(now: float | None, before: float | None, pct: bool) -> str:
    if now is None or before is None or abs(now - before) < 1e-9:
        return ""
    d = now - before
    return f" ({'+' if d > 0 else ''}{d * 100:.0f}pt)" if pct else f" ({d:+.1f})"


def table(summary: dict[str, Any], baseline: dict[str, Any] | None = None) -> str:
    """The per-scenario table, with changes against a baseline summary when given."""
    old = (baseline or {}).get("scenarios", {})
    lines = [
        f"{'scenario':<38} {'runs':>4} {'pass':>11} {'checks':>11} {'judge':>10} {'cost':>8}",
        "-" * 87,
    ]
    for sid, s in summary["scenarios"].items():
        b = old.get(sid, {})
        lines.append(
            f"{sid:<38} {s['runs']:>4} "
            f"{_pct(s['pass_rate']) + _delta(s['pass_rate'], b.get('pass_rate'), True):>11} "
            f"{_pct(s['check_pass_rate']):>11} "
            f"{_judge(s['judge']) + _delta(s['judge'], b.get('judge'), False):>10} "
            f"${s['cost_usd']:>7.4f}"
        )
    o = summary["overall"]
    bo = (baseline or {}).get("overall", {})
    lines += [
        "-" * 87,
        f"{'all':<38} {o['runs']:>4} "
        f"{_pct(o['pass_rate']) + _delta(o['pass_rate'], bo.get('pass_rate'), True):>11} "
        f"{_pct(o['check_pass_rate']):>11} "
        f"{_judge(o['judge']) + _delta(o['judge'], bo.get('judge'), False):>10} "
        f"${o['agent_cost_usd']:>7.4f}",
    ]
    if o["judge_cost_usd"]:
        lines.append(f"{'':<38} judging cost ${o['judge_cost_usd']:.4f}")
    return "\n".join(lines)


def failures(summary: dict[str, Any]) -> str:
    out = []
    for sid, s in summary["scenarios"].items():
        for name, n in s["failures"].items():
            out.append(f"  {sid}: {name} ({n}/{s['runs']})")
    return "\n".join(out)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    raise TypeError(type(value))


def save(
    results: list[RunResult], summary: dict[str, Any], meta: dict[str, Any], path: Path
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"meta": meta, **summary, "runs": [asdict(r) for r in results]}
    path.write_text(json.dumps(payload, indent=1, default=_jsonable))
    return path
