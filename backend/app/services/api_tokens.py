"""Personal access tokens: who a token belongs to, and keeping "last used" roughly current."""

from datetime import timedelta

from sqlmodel import Session, select

from app.core.security import API_TOKEN_PREFIX, hash_api_token
from app.models import ApiToken, User, utcnow

# don't write to the database on every call just to bump "last used"
_TOUCH_EVERY = timedelta(minutes=5)


def user_for_token(session: Session, token: str | None) -> User | None:
    """The active user a personal access token belongs to, or None."""
    if not token or not token.startswith(API_TOKEN_PREFIX):
        return None
    row = session.exec(select(ApiToken).where(ApiToken.token_hash == hash_api_token(token))).first()
    if row is None:
        return None
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        return None
    now = utcnow()
    if row.last_used_at is None or now - row.last_used_at > _TOUCH_EVERY:
        row.last_used_at = now
        session.add(row)
        session.commit()
    return user


def bearer(authorization: str | None) -> str | None:
    """The token from an "Authorization: Bearer …" header."""
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None
