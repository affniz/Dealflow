"""Security headers on every response.

The Content-Security-Policy is the important one: the app loads only its own scripts and
styles (Vite builds them into /assets), so even if someone got markup into a page, say through
a deal title or a note, the browser wouldn't run a script from it or send data anywhere else.
"""

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from app.core.config import settings

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]

CSP = "; ".join(
    [
        "default-src 'self'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",  # the favicon is a data: URL
        "font-src 'self'",
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        "frame-ancestors 'none'",  # nobody can put the app in a frame (clickjacking)
    ]
)
# FastAPI's API docs page loads Swagger UI from a CDN with an inline script
DOCS_PATHS = ("/docs",)


def security_headers(path: str) -> list[tuple[bytes, bytes]]:
    headers = {
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
        # links out of the app don't tell other sites which page they came from
        "Referrer-Policy": "no-referrer",
        "Cross-Origin-Opener-Policy": "same-origin",
        "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    }
    if not path.startswith(DOCS_PATHS):
        headers["Content-Security-Policy"] = CSP
    if settings.ENVIRONMENT == "production":  # served over HTTPS there; stay on it
        headers["Strict-Transport-Security"] = "max-age=31536000"
    return [(k.lower().encode(), v.encode()) for k, v in headers.items()]


class SecurityHeaders:
    """Plain ASGI middleware (not BaseHTTPMiddleware), so streamed responses like the MCP
    endpoint's pass straight through."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = security_headers(scope["path"])

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                present = {name.lower() for name, _ in message.get("headers", [])}
                message["headers"] = [
                    *message.get("headers", []),
                    *(h for h in extra if h[0] not in present),
                ]
            await send(message)

        await self.app(scope, receive, send_with_headers)
