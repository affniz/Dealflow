"""Personal access tokens: who a token belongs to, what it may do, and whether it still works.

A token acts as its owner, with their role and access, until it expires or is revoked. Its scope
narrows that further: a "read" token can only look things up; a "suggest" token can also
propose changes, which still wait in the owner's Agent inbox for their approval.
"""

from dataclasses import dataclass
from datetime import timedelta

from sqlmodel import Session, select

from app.core.security import API_TOKEN_PREFIX, hash_api_token
from app.models import ApiToken, User, utcnow

# don't write to the database on every call just to bump "last used"
_TOUCH_EVERY = timedelta(minutes=5)

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

    @property
    def can_suggest(self) -> bool:
        return self.scope == "suggest"


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
            f"This access token expired on {row.expires_at:%d %b %Y}. "
            "Create a new one in Dealflow under Your account."
        )
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise TokenRefused(NO_TOKEN)
    if row.last_used_at is None or now - row.last_used_at > _TOUCH_EVERY:
        row.last_used_at = now
        session.add(row)
        session.commit()
    return TokenAccess(user=user, scope=row.scope)


def bearer(authorization: str | None) -> str | None:
    """The token from an "Authorization: Bearer …" header."""
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None
