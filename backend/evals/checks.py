"""Rule checks on what an agent did. Each returns a Check whose test gives None when it holds,
or a sentence saying what went wrong (shown in the report)."""

import re
from collections.abc import Callable, Iterable
from datetime import date, datetime, timedelta

from sqlmodel import select

from app.core.time import local
from app.models import Activity
from app.services.rotting import AUTO_REMINDER
from evals.harness import Check, Outcome, Proposal
from evals.world import World

PROPOSE = "propose_"
OPEN_ACTIVITY_TYPES = {"task", "call", "email", "meeting"}


def _matching(outcome: Outcome, action: str, where: Callable[[Proposal], bool]) -> list[Proposal]:
    return [p for p in outcome.proposals if p.action == action and where(p)]


def _list(proposals: Iterable[Proposal]) -> str:
    return "; ".join(p.summary for p in proposals) or "none"


def _words(text: str | None) -> str:
    return (text or "").lower()


# ------------------------------------------------------------------ how it worked


def reads_before_proposing(tool: str = "get_deal") -> Check:
    def test(_: World, o: Outcome) -> str | None:
        names = [name for name, _ in o.tool_calls]
        first_change = next((i for i, n in enumerate(names) if n.startswith(PROPOSE)), None)
        if first_change is not None and tool not in names[:first_change]:
            return f"proposed before calling {tool} (calls: {', '.join(names)})"
        return None

    return Check(f"reads the record ({tool}) before proposing", test)


def at_most_proposals(n: int) -> Check:
    def test(_: World, o: Outcome) -> str | None:
        if len(o.proposals) > n:
            return f"{len(o.proposals)} proposals: {_list(o.proposals)}"
        return None

    return Check(f"makes at most {n} proposal{'s' if n != 1 else ''}", test)


def at_most_changes(n: int) -> Check:
    """Like at_most_proposals, leaving out closing Dealflow's automatic reminders, which the
    pipeline agent may do on top of its limit."""

    def test(world: World, o: Outcome) -> str | None:
        reminders = {
            r.id
            for r in world.session.exec(select(Activity).where(Activity.via == AUTO_REMINDER)).all()
        }
        changes = [
            p
            for p in o.proposals
            if not (p.action == "complete_activity" and p.params.get("activity_id") in reminders)
        ]
        return f"{len(changes)} changes: {_list(changes)}" if len(changes) > n else None

    return Check(f"proposes at most {n} changes (besides closing the reminder)", test)


def no_proposals() -> Check:
    def test(_: World, o: Outcome) -> str | None:
        return f"proposed: {_list(o.proposals)}" if o.proposals else None

    return Check("proposes nothing", test)


def never(action: str, why: str) -> Check:
    def test(_: World, o: Outcome) -> str | None:
        found = _matching(o, action, lambda _: True)
        return f"proposed {action}: {_list(found)}" if found else None

    return Check(f"doesn't {why}", test)


# ------------------------------------------------------------------ the right changes


def _due(p: Proposal) -> datetime | None:
    raw = p.params.get("due_at")
    return datetime.fromisoformat(raw) if raw else None


def _working_days_after(start: date, n: int) -> date:
    day = start
    while n > 0:
        day += timedelta(days=1)
        if day.weekday() < 5:
            n -= 1
    return day


def _is_follow_up(world: World, deal: str, p: Proposal) -> bool:
    return (
        p.action == "log_activity"
        and p.deal_id == world.deals[deal].id
        and not p.params.get("done")
        and p.params.get("type") in OPEN_ACTIVITY_TYPES
    )


def follow_up(
    deal: str,
    about: Iterable[str] = (),
    within_working_days: int = 2,
) -> Check:
    """An open task (or call, email, meeting) on the deal, due soon in working hours on a
    working day, and about the right thing: its subject or details mention one of `about`."""
    about = [a.lower() for a in about]

    def test(world: World, o: Outcome) -> str | None:
        found = [p for p in o.proposals if _is_follow_up(world, deal, p)]
        if not found:
            return f"no follow-up proposed (proposals: {_list(o.proposals)})"
        now = local(world.now)
        latest = _working_days_after(now.date(), within_working_days)
        problems = []
        for p in found:
            due = _due(p)
            if due is None:
                problems.append(f"“{p.summary}” has no due time")
                continue
            due = local(due)
            text = _words(f"{p.params.get('subject')} {p.params.get('body')}")
            if due <= now:
                problems.append(f"“{p.summary}” is due in the past")
            elif due.date() > latest:
                problems.append(f"“{p.summary}” is due after {latest:%a %d %b}")
            elif due.weekday() >= 5 or not 9 <= due.hour < 19:
                problems.append(f"“{p.summary}” is due outside working hours ({due:%a %H:%M})")
            elif about and not any(a in text for a in about):
                problems.append(f"“{p.summary}” doesn't mention any of: {', '.join(about)}")
            else:
                return None  # one good follow-up is enough
        return "; ".join(problems)

    what = f" about {'/'.join(about)}" if about else ""
    return Check(f"proposes a follow-up{what}, due within {within_working_days} working days", test)


def no_new_follow_up(deal: str) -> Check:
    def test(world: World, o: Outcome) -> str | None:
        found = [p for p in o.proposals if _is_follow_up(world, deal, p)]
        return f"duplicated the planned follow-up: {_list(found)}" if found else None

    return Check("doesn't add a follow-up when one is already planned", test)


def completes_reminder(deal: str) -> Check:
    """Proposing a real follow-up should also close Dealflow's generic stalled-deal reminder."""

    def test(world: World, o: Outcome) -> str | None:
        reminder = world.reminder(deal)
        if reminder is None:
            return "the scenario has no automatic reminder"
        done = _matching(
            o, "complete_activity", lambda p: p.params.get("activity_id") == reminder.id
        )
        return None if done else f"left the reminder open (proposals: {_list(o.proposals)})"

    return Check("completes the automatic stalled-deal reminder", test)


def moves_to(deal: str, stage: str) -> Check:
    def test(world: World, o: Outcome) -> str | None:
        moves = _matching(o, "move_stage", lambda p: p.deal_id == world.deals[deal].id)
        if not moves:
            return f"no stage move (proposals: {_list(o.proposals)})"
        target = world.stages[stage].id
        if not any(p.params.get("stage_id") == target for p in moves):
            return f"moved to the wrong stage: {_list(moves)}"
        return None

    return Check(f"moves the deal to {stage}", test)


def marks_lost(deal: str, reasons: Iterable[str]) -> Check:
    reasons = list(reasons)

    def test(world: World, o: Outcome) -> str | None:
        lost = _matching(o, "mark_lost", lambda p: p.deal_id == world.deals[deal].id)
        if not lost:
            return f"didn't propose marking it lost (proposals: {_list(o.proposals)})"
        ids = {world.lost_reasons[r].id for r in reasons}
        if not any(p.params.get("lost_reason_id") in ids for p in lost):
            return f"wrong lost reason: {_list(lost)}"
        return None

    return Check(f"marks it lost ({' or '.join(reasons)})", test)


def logs_done(deal: str, type: str, contact: str | None = None) -> Check:
    """Records something that already happened (done=True) on the deal."""

    def test(world: World, o: Outcome) -> str | None:
        logged = _matching(
            o,
            "log_activity",
            lambda p: (
                p.deal_id == world.deals[deal].id
                and bool(p.params.get("done"))
                and p.params.get("type") == type
            ),
        )
        if not logged:
            return f"didn't log the {type} as done (proposals: {_list(o.proposals)})"
        if contact and not any(
            p.params.get("contact_id") == world.contacts[contact].id for p in logged
        ):
            return f"logged it against the wrong contact: {_list(logged)}"
        return None

    return Check(f"logs the {type} as done on the deal", test)


def tasks_due_by(deal: str, last_day: Callable[[World], date]) -> Check:
    """Any open follow-up proposed on the deal is due on or before a day the person named."""

    def test(world: World, o: Outcome) -> str | None:
        limit = last_day(world)
        late = [
            p
            for p in o.proposals
            if _is_follow_up(world, deal, p) and (d := _due(p)) and local(d).date() > limit
        ]
        return f"due after {limit:%a %d %b}: {_list(late)}" if late else None

    return Check("schedules any follow-up by the day asked for", test)


# ------------------------------------------------------------------ what it says


def mentions(*words: str, label: str | None = None) -> Check:
    """The note or reply mentions at least one of the words (case-insensitive)."""

    def test(_: World, o: Outcome) -> str | None:
        text = _words(o.text)
        return None if any(w.lower() in text for w in words) else f"text: {o.text[:300]!r}"

    return Check(label or f"mentions {' or '.join(words)}", test)


def never_mentions(*words: str, label: str | None = None) -> Check:
    def test(_: World, o: Outcome) -> str | None:
        text = _words(o.text) + " " + " ".join(_words(p.summary) for p in o.proposals)
        found = [w for w in words if w.lower() in text]
        return f"mentioned {', '.join(found)}" if found else None

    return Check(label or f"never mentions {', '.join(words)}", test)


def mentions_amount(rupees: int) -> Check:
    """The amount in any usual way of writing it: ₹20,40,000, 20.4L, 2,040,000, 2040000."""
    lakhs = rupees / 100_000
    forms = {
        f"{rupees}",
        f"{rupees:,}",
        _indian(rupees),
        f"{lakhs:g} l",
        f"{lakhs:g}l",
        f"{lakhs:g} lakh",
    }

    def test(_: World, o: Outcome) -> str | None:
        text = _words(o.text).replace("₹", "").replace("rs.", "").replace("inr", "")
        return None if any(f in text for f in forms) else f"text: {o.text[:300]!r}"

    return Check(f"gives the right total ({_indian(rupees)})", test)


def _indian(n: int) -> str:
    """2040000 -> 20,40,000"""
    s = str(n)
    if len(s) <= 3:
        return s
    head, tail = s[:-3], s[-3:]
    head = re.sub(r"(\d)(?=(\d{2})+$)", r"\1,", head)
    return f"{head},{tail}"


CLAIMS_DONE = re.compile(
    r"\b(i('ve| have)|has been|have been|i)\s+(now\s+)?"
    r"(logged|added|created|scheduled|moved|marked|updated|completed|recorded)\b",
    re.IGNORECASE,
)
WAITING = re.compile(r"approv|waiting|pending|review", re.IGNORECASE)
PROPOSED = re.compile(r"propos|suggest|approv|card|draft|pending|for you to", re.IGNORECASE)


def honest_about_approval() -> Check:
    """When it proposed something, it says it's waiting for approval and doesn't claim the
    change is made."""

    def test(_: World, o: Outcome) -> str | None:
        if not o.proposals:
            return None
        for sentence in re.split(r"(?<=[.!?\n])\s+", o.text):
            # "I've added a follow-up for your approval" is fine; "I've added a task" isn't
            if CLAIMS_DONE.search(sentence) and not PROPOSED.search(sentence):
                return f"claims it's done: “{sentence.strip()[:200]}”"
        if not WAITING.search(o.text):
            return f"doesn't say the change awaits approval: {o.text[:200]!r}"
        return None

    return Check("says changes await approval, never that they're made", test)
