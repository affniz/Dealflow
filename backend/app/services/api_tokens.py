"""Personal access tokens: who a token belongs to, what it may do, and whether it still works.

A token acts as its owner, with their role and access, until it expires or is revoked. Its scope
narrows that further: a "read" token can only look things up; a "suggest" token can also
propose changes, which still wait in the owner's Agent inbox for their approval.

In a token's last week its owner hears about it twice over: Claude's tool results carry a notice
(see app.mcp_server), and the worker emails them once (warn_expiring, when SMTP is set up).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.core.security import API_TOKEN_PREFIX, hash_api_token
from app.core.time import describe, local
from app.models import ApiToken, Role, User, utcnow
from app.services.email import send_email

# don't write to the database on every call just to bump "last used"
_TOUCH_EVERY = timedelta(minutes=5)
# An expired token stays listed (and its 401 says when it expired) for this long, so people can
# see why Claude stopped working; then the worker's hourly cleanup deletes it.
KEEP_EXPIRED = timedelta(days=30)
# how long before a token expires its owner is told, so they can replace it in time
WARN_BEFORE = timedelta(days=7)

NO_TOKEN = (
    "Send a Dealflow personal access token as 'Authorization: Bearer dfp_…'. "
    "Create one in Dealflow under Your account."
)


class TokenRefused(Exception):
    """The token doesn't sign anyone in; the message says why, for the person using it."""


@dataclass
class TokenAccess:
    user: User
    scope: str
    expires_at: datetime

    @property
    def can_suggest(self) -> bool:
        """Whether the proposal tools are any use: the token allows them, and so does the
        person's role (a viewer's "suggest" token still can't propose)."""
        return self.scope == "suggest" and self.user.role != Role.viewer

    def expiry_notice(self, now: datetime | None = None) -> str | None:
        """In the token's last WARN_BEFORE, what to tell the person using it; otherwise None."""
        if self.expires_at - (now or utcnow()) > WARN_BEFORE:
            return None
        return (
            f"This access token stops working on {describe(self.expires_at)}. To keep Claude "
            "connected to Dealflow, create a new token under Your account, add it to Claude, "
            "and revoke this one."
        )


def token_access(session: Session, token: str | None) -> TokenAccess:
    """Who a personal access token signs in as, and what it may do; raises TokenRefused."""
    if not token or not token.startswith(API_TOKEN_PREFIX):
        raise TokenRefused(NO_TOKEN)
    row = session.exec(select(ApiToken).where(ApiToken.token_hash == hash_api_token(token))).first()
    if row is None:
        raise TokenRefused(NO_TOKEN)
    now = utcnow()
    if row.expires_at <= now:
        raise TokenRefused(
            f"This access token expired on {local(row.expires_at):%d %b %Y}. "
            "Create a new one in Dealflow under Your account."
        )
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise TokenRefused(NO_TOKEN)
    if row.last_used_at is None or now - row.last_used_at > _TOUCH_EVERY:
        row.last_used_at = now
        session.add(row)
        session.commit()
    return TokenAccess(user=user, scope=row.scope, expires_at=row.expires_at)


def warn_expiring(session: Session, now: datetime | None = None) -> tuple[int, int]:
    """Email each person whose tokens expire within WARN_BEFORE, once per token: the worker
    asks every hour. A token that was never used isn't mentioned, since nothing stops working
    when it expires. Returns (emails sent, emails that couldn't be sent); those are tried again
    next time."""
    now = now or utcnow()
    rows = session.exec(
        select(ApiToken, User)
        .join(User, col(User.id) == col(ApiToken.user_id))
        .where(
            col(ApiToken.expires_at) > now,
            col(ApiToken.expires_at) <= now + WARN_BEFORE,
            col(ApiToken.expiry_warned_at).is_(None),
            col(ApiToken.last_used_at).is_not(None),
            col(User.is_active).is_(True),
        )
        .order_by(col(ApiToken.expires_at))
    ).all()
    by_person: dict[int, tuple[User, list[ApiToken]]] = {}
    for token, user in rows:
        by_person.setdefault(user.id, (user, []))[1].append(token)  # type: ignore[arg-type]

    sent = failed = 0
    for user, tokens in by_person.values():
        if not send_email(user.email, *_expiry_email(tokens)):
            failed += 1
            continue
        for t in tokens:
            t.expiry_warned_at = now
            session.add(t)
        session.commit()  # each person's, so a later failure doesn't email them twice
        sent += 1
    return sent, failed


def _expiry_email(tokens: list[ApiToken]) -> tuple[str, str]:
    """Subject and body. Token names stay out of the subject: they're free text."""
    app_url = (settings.APP_URL or "http://localhost:5173").rstrip("/")
    listed = "\n".join(f"- {t.name} ({t.prefix}…): {describe(t.expires_at)}" for t in tokens)
    if len(tokens) == 1:
        subject = "Dealflow: your access token expires soon"
        intro = "This personal access token, for connecting Claude to Dealflow, stops working:"
    else:
        subject = f"Dealflow: {len(tokens)} of your access tokens expire soon"
        intro = "These personal access tokens, for connecting Claude to Dealflow, stop working:"
    body = (
        f"{intro}\n\n{listed}\n\n"
        "After that, Claude (or anything else using it) can't connect to Dealflow. To keep it "
        f"connected, create a new token at {app_url}/account#connect-claude, add it to Claude "
        "with the command shown there, and revoke the old one.\n\n"
        "You get this email once for each token.\n"
    )
    return subject, body


def purge_expired_tokens(session: Session, now: datetime | None = None) -> int:
    """Delete tokens that expired more than KEEP_EXPIRED ago, anyone's. Commits."""
    cutoff = (now or utcnow()) - KEEP_EXPIRED
    deleted = session.exec(delete(ApiToken).where(col(ApiToken.expires_at) <= cutoff))
    session.commit()
    return deleted.rowcount or 0


def bearer(authorization: str | None) -> str | None:
    """The token from an "Authorization: Bearer …" header."""
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None
