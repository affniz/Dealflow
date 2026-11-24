"""Answering Copilot messages in the background.

A reply can take a minute (several model calls). Answering inside the HTTP request kept the
browser waiting with nothing to show and held one of the API's request threads the whole time,
so a few busy chats could slow the whole app. Instead, POST /copilot/messages starts the turn
here and returns at once; the turn saves each step as it goes (AgentConversation.turn_progress),
and the chat polls the conversation until it's done.

Turns run in a small pool of their own (COPILOT_CONCURRENCY at once; more wait), each with its
own database session, holding a connection only between model calls.
"""

import logging
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import AbstractContextManager, contextmanager
from datetime import datetime, timedelta
from typing import Any

from sqlmodel import Session, col, select

from app.agent import copilot
from app.agent.loop import MessagesClient
from app.agent.usage import persist_after_failure
from app.core.config import settings
from app.core.db import engine
from app.models import AgentConversation, AgentProposal, AIUsage, ProposalStatus, User, utcnow
from app.services.budgets import BudgetExceeded

log = logging.getLogger(__name__)

# a turn that started longer ago than this died with its server process, if nothing else ended it
TURN_TIMEOUT = timedelta(minutes=10)

INTERRUPTED = "Copilot's reply was interrupted (the server restarted). Send your message again."
UNREACHABLE = "Copilot couldn't reach Claude just now. Try again."
BROKE = "Copilot hit an error answering this. Try again; if it keeps happening, tell your admin."

_pool = ThreadPoolExecutor(max_workers=settings.COPILOT_CONCURRENCY, thread_name_prefix="copilot")
# the turns this process is answering: (conversation id, the turn's turn_started_at)
_running: set[tuple[int, datetime]] = set()
_lock = threading.Lock()


@contextmanager
def _own_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


# Replaced in tests: the turn then runs straight away, on the test's own session.
session_scope: Callable[[], AbstractContextManager[Session]] = _own_session
run_in_background: Callable[..., Any] = _pool.submit


def start(
    conversation_id: int,
    user_id: int,
    text: str,
    deal_id: int | None,
    client: MessagesClient,
    started: datetime,
) -> None:
    """Answer the message in the background. The conversation is already marked as
    answering (turn_started_at = `started`, which names this turn), and its message is shown
    from the first progress save."""
    with _lock:
        _running.add((conversation_id, started))
    run_in_background(_answer, conversation_id, user_id, text, deal_id, client, started)


def _answer(
    conversation_id: int,
    user_id: int,
    text: str,
    deal_id: int | None,
    client: MessagesClient,
    started: datetime,
) -> None:
    import anthropic

    try:
        with session_scope() as session:
            conv = session.get(AgentConversation, conversation_id)
            user = session.get(User, user_id)
            if conv is None or user is None or conv.turn_started_at != started:
                return  # deleted, or given up on while it waited and another message took over
            billed: list[AIUsage] = []
            try:
                copilot.run_turn(
                    session, client, user, conv, text, deal_id, usage_sink=billed, turn=started
                )
            except copilot.TurnSuperseded:
                # it ran past TURN_TIMEOUT and a newer message took the chat: that turn already
                # withdrew this one's committed proposals, and the rest are rolled back here
                session.rollback()
                persist_after_failure(session, billed)
                log.warning("Copilot turn in conversation %s was replaced", conversation_id)
            except Exception as exc:
                session.rollback()
                persist_after_failure(session, billed)  # calls made before it failed are billed
                if isinstance(exc, BudgetExceeded):  # spent in another tab meanwhile
                    message = str(exc)
                elif isinstance(exc, anthropic.APIError):
                    log.warning("Copilot call failed: %s", exc)
                    message = UNREACHABLE
                else:
                    log.exception("Copilot turn failed")
                    message = BROKE
                end_failed_turn(session, conversation_id, started, message, text)
    except Exception:
        log.exception("Couldn't record the end of Copilot turn %s", conversation_id)
    finally:
        with _lock:
            _running.discard((conversation_id, started))


def end_failed_turn(
    session: Session,
    conversation_id: int,
    started: datetime,
    message: str,
    text: str,
    commit: bool = True,
) -> None:
    """A failed turn isn't added to the chat. Its proposals were committed as it went, so
    withdraw them; record why it failed; and let the next message in.

    Only the turn named by `started` is ended: if a newer message has taken the conversation
    over meanwhile, this does nothing."""
    conv = session.exec(
        select(AgentConversation)
        .where(AgentConversation.id == conversation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).first()
    if conv is None or conv.turn_started_at != started:
        if commit:
            session.commit()  # release the lock
        return
    conv.turn_started_at = None
    conv.turn_progress = None
    conv.turn_error = {"message": message, "text": text}
    session.add(conv)
    stmt = select(AgentProposal).where(
        AgentProposal.conversation_id == conversation_id,
        AgentProposal.status == ProposalStatus.pending,
        col(AgentProposal.created_at) >= started,
    )
    for p in session.exec(stmt):
        p.status = ProposalStatus.failed
        p.error = "Copilot's reply didn't finish, so this suggestion was withdrawn"
        session.add(p)
    if commit:
        session.commit()


def turn_text(conv: AgentConversation) -> str:
    """The message the current (or a dead) turn was answering."""
    first = (conv.turn_progress or [{}])[0]
    content = first.get("content")
    return content if first.get("role") == "user" and isinstance(content, str) else ""


def is_stale(conv: AgentConversation, now: datetime | None = None) -> bool:
    started = conv.turn_started_at
    return started is not None and (now or utcnow()) - started >= TURN_TIMEOUT


def interrupt_all() -> None:
    """On shutdown: turns this process was answering won't finish, so say so now rather than
    leave the chat waiting until TURN_TIMEOUT."""
    with _lock:
        ours = list(_running)
    _pool.shutdown(wait=False, cancel_futures=True)
    if not ours:
        return
    with session_scope() as session:
        for conv_id, started in ours:
            conv = session.get(AgentConversation, conv_id)
            if conv is not None:  # ends it only if it's still this turn, not a newer one
                end_failed_turn(session, conv_id, started, INTERRUPTED, turn_text(conv))
    log.info("Interrupted %d Copilot replies on shutdown", len(ours))
