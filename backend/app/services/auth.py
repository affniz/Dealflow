"""Sign-in sessions and limits on password guessing.

A sign-in creates an AuthSession row; the token handed out (a signed JWT, in an httpOnly cookie
for the browser) names that row, and every request checks the row is still there and in date.
So signing out, changing a password or deactivating someone ends their sessions at once,
instead of leaving a stolen token working until it expires.

Failed sign-ins are counted per email from one address and per address, over a sliding
window; past the limit, that address waits instead of getting another guess. Counting the
email together with the address means a stranger can't lock someone out of their account
by mistyping their password on purpose.
"""

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import jwt
from fastapi import HTTPException, status
from sqlalchemy import func, or_
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.core.security import ALGORITHM, hash_password, verify_password
from app.models import AuthSession, LoginFailure, User, utcnow

# a session's last_used_at is saved at most this often, not on every request
TOUCH_EVERY = timedelta(minutes=5)
# checked when the email is unknown, so a wrong email takes as long as a wrong password
_DUMMY_HASH = hash_password("not-anyone's-password")


def _idle() -> timedelta:
    return timedelta(minutes=settings.SESSION_IDLE_MINUTES)


def _window() -> timedelta:
    return timedelta(minutes=settings.LOGIN_WINDOW_MINUTES)


# ------------------------------------------------------------------ sign-in and rate limits


def _too_many(retry_after: timedelta) -> HTTPException:
    minutes = max(1, math.ceil(retry_after.total_seconds() / 60))
    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        f"Too many failed sign-ins. Try again in {minutes} minute{'s' if minutes > 1 else ''}.",
        headers={"Retry-After": str(max(1, math.ceil(retry_after.total_seconds())))},
    )


def _check_limits(session: Session, email: str, ip: str, now: datetime) -> None:
    since = now - _window()
    for where, limit in (
        ((LoginFailure.email == email, LoginFailure.ip == ip), settings.LOGIN_MAX_FAILURES),
        ((LoginFailure.ip == ip,), settings.LOGIN_MAX_FAILURES_PER_IP),
    ):
        count, oldest = session.exec(
            select(func.count(), func.min(LoginFailure.created_at)).where(
                col(LoginFailure.created_at) > since, *where
            )
        ).one()
        if count >= limit:
            # the oldest failure in the window has to age out before another try
            raise _too_many(oldest + _window() - now)


def authenticate(session: Session, email: str, password: str, ip: str) -> User:
    """The user with this email and password, or an HTTPException (400, or 429 when this
    address has failed too often lately)."""
    email = email.lower()
    now = utcnow()
    _check_limits(session, email, ip, now)
    user = session.exec(select(User).where(User.email == email)).first()
    if not verify_password(password, user.hashed_password if user else _DUMMY_HASH) or not user:
        session.exec(delete(LoginFailure).where(col(LoginFailure.created_at) <= now - _window()))
        session.add(LoginFailure(email=email[:255], ip=ip[:64], created_at=now))
        session.commit()
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect email or password")
    if not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Inactive user")
    session.exec(delete(LoginFailure).where(LoginFailure.email == email, LoginFailure.ip == ip))
    return user


# ------------------------------------------------------------------ sessions


def start_session(session: Session, user: User, user_agent: str | None) -> tuple[str, datetime]:
    """Sign this user in: returns the token and when it expires (at the latest)."""
    now = utcnow()
    # tidy up: sessions that have run out, anyone's
    session.exec(
        delete(AuthSession).where(
            or_(col(AuthSession.expires_at) <= now, col(AuthSession.last_used_at) <= now - _idle())
        )
    )
    expires = now + timedelta(days=settings.SESSION_MAX_DAYS)
    row = AuthSession(
        user_id=user.id,  # type: ignore[arg-type]
        created_at=now,
        last_used_at=now,
        expires_at=expires,
        user_agent=(user_agent or "")[:255] or None,
    )
    session.add(row)
    session.commit()
    token = jwt.encode(
        {"sub": str(user.id), "sid": row.id, "exp": expires}, settings.SECRET_KEY, ALGORITHM
    )
    return token, expires


@dataclass
class SignedIn:
    user: User
    auth_session: AuthSession


def resolve(session: Session, token: str) -> SignedIn | None:
    """Who this token signs in, if its session is still going; touches the session."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        user_id, session_id = int(payload["sub"]), int(payload["sid"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return None
    row = session.get(AuthSession, session_id)
    now = utcnow()
    if (
        row is None
        or row.user_id != user_id
        or row.expires_at <= now
        or row.last_used_at <= now - _idle()
    ):
        return None
    user = session.get(User, user_id)
    if user is None or not user.is_active:
        return None
    if now - row.last_used_at >= TOUCH_EVERY:
        row.last_used_at = now
        session.add(row)
        session.commit()
    return SignedIn(user, row)


def end_session(session: Session, token: str) -> None:
    """Sign out the session this token names, if it's still there."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        session_id = int(payload["sid"])
    except (jwt.InvalidTokenError, KeyError, ValueError, TypeError):
        return
    session.exec(delete(AuthSession).where(AuthSession.id == session_id))
    session.commit()


def end_sessions(session: Session, user_id: int, keep: int | None = None) -> None:
    """Sign this person out everywhere (except the session `keep`). Doesn't commit."""
    stmt = delete(AuthSession).where(AuthSession.user_id == user_id)
    if keep is not None:
        stmt = stmt.where(AuthSession.id != keep)
    session.exec(stmt)
