"""A request ID and a log line for every request, and a useful answer when one crashes."""

import logging
import re
import secrets
import time

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.headers import ASGIApp, Message, Receive, Scope, Send
from app.core.logs import request_id

log = logging.getLogger("app.requests")

REQUEST_ID_HEADER = "X-Request-ID"
# an ID from a proxy in front of the app is kept, if it looks like one
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# these get a line only at DEBUG: the health check every few seconds, and static files
_QUIET_PREFIXES = ("/health", "/assets/")


def _incoming_id(scope: Scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name == b"x-request-id":
            candidate = value.decode("latin-1")
            return candidate if _VALID_ID.match(candidate) else None
    return None


class RequestLog:
    """Plain ASGI middleware, like SecurityHeaders, so streamed responses pass straight
    through. Logs method, path (not the query string, which can hold search terms), status,
    time taken and who was signed in."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rid = _incoming_id(scope) or secrets.token_hex(6)
        # Not reset afterwards: if the request crashes, the server logs the traceback after
        # this returns, and the ID should be on that line too. Each request is its own task,
        # so it never leaks into the next one.
        request_id.set(rid)
        started = time.perf_counter()
        status = 500

        async def send_with_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message["headers"] = [
                    *message.get("headers", []),
                    (REQUEST_ID_HEADER.lower().encode(), rid.encode()),
                ]
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            path = scope["path"]
            user = scope.get("state", {}).get("user")  # set when the request signed in
            level = logging.DEBUG if path.startswith(_QUIET_PREFIXES) else logging.INFO
            if status >= 500:
                # not ERROR: a crash's traceback is logged (and reported) once, by the server
                level = logging.WARNING
            log.log(
                level,
                "%s %s %s",
                scope["method"],
                path,
                status,
                extra={
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "user_id": getattr(user, "id", None),
                },
            )


def server_error(_: Request, exc: Exception) -> JSONResponse:
    """The answer to a request that crashed: a reference the person can pass on, which finds
    the traceback in the logs (and in Sentry). The error itself stays private."""
    rid = request_id.get()
    detail = "Something went wrong on our side."
    if rid:
        detail += f" If it keeps happening, mention reference {rid}."
    return JSONResponse(
        {"detail": detail},
        status_code=500,
        headers={REQUEST_ID_HEADER: rid} if rid else None,
    )
