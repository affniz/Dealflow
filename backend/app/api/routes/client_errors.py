"""Errors in people's browsers, reported by the app so they show up in the logs (and in
Sentry, which picks up anything logged at ERROR) instead of only in that browser's console.

Anyone can report, signed in or not: the sign-in pages can break too. So nothing is trusted
from it beyond being an error report: sizes are capped, each address may send only a few a
minute, and it only ever becomes a log line.
"""

import logging
import time
from collections import defaultdict, deque

from fastapi import APIRouter, Request, Response, status

from app.api.routes.login import client_ip
from app.models import ClientError

router = APIRouter(prefix="/client-errors", tags=["client-errors"])
log = logging.getLogger("app.browser")

PER_MINUTE = 10
_recent: defaultdict[str, deque[float]] = defaultdict(deque)


def _allowed(ip: str, now: float) -> bool:
    """At most PER_MINUTE reports per address per minute (counted in this process)."""
    if len(_recent) > 10_000:  # don't let a flood of addresses grow this without bound
        _recent.clear()
    times = _recent[ip]
    while times and now - times[0] > 60:
        times.popleft()
    if len(times) >= PER_MINUTE:
        return False
    times.append(now)
    return True


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
def report_client_error(request: Request, body: ClientError) -> Response:
    """The app reports a crash in someone's browser. Always answers 204, even when the
    report is dropped for coming too often."""
    if _allowed(client_ip(request), time.monotonic()):
        log.error(
            "Browser error on %s: %s",
            body.path,
            body.message,
            extra={
                "stack": body.stack,
                "component_stack": body.component_stack,
                "release": body.release,
                "user_agent": request.headers.get("user-agent", "")[:300],
            },
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
