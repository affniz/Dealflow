"""Resetting a forgotten password with a one-time link.

Two ways to get a link:
- "Forgot your password?" emails one, valid for an hour, if SMTP is set up (while developing
  without SMTP, the link goes to the API's log instead).
- An admin makes one for someone on the team, valid for a day, and passes it on themselves.

A link works once. Making a new one cancels the person's older links, and using one signs them
out everywhere (whoever forgot or lost the password may not be the only one who had it).
The secret goes after a # in the link, so browsers never send it to the server in a request
line or a Referer header; the reset page posts it in the request body.
"""

import logging
import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage

from fastapi import HTTPException, status
from sqlmodel import Session, col, delete, select

from app.core.config import settings
from app.core.security import generate_api_token, hash_api_token, hash_password
from app.models import LoginFailure, PasswordResetToken, User, utcnow
from app.services.auth import end_sessions

log = logging.getLogger(__name__)

EMAILED_LINK_LIFETIME = timedelta(hours=1)
ADMIN_LINK_LIFETIME = timedelta(hours=24)
# one emailed link per person per this long, so nobody can flood someone's inbox
EMAIL_EVERY = timedelta(minutes=5)
INVALID = "This reset link is invalid or has expired. Ask for a new one."


def create_link(
    session: Session, user: User, lifetime: timedelta, created_by: User | None = None
) -> tuple[str, datetime]:
    """A new reset link's secret for this person (cancelling their older ones), and its
    expiry. Commits."""
    token = generate_api_token()  # long and random, like a personal access token
    expires = utcnow() + lifetime
    session.exec(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    session.add(
        PasswordResetToken(
            user_id=user.id,  # type: ignore[arg-type]
            token_hash=hash_api_token(token),
            expires_at=expires,
            created_by_id=created_by.id if created_by else None,
        )
    )
    session.commit()
    return token, expires


def reset_url(token: str) -> str:
    return f"{(settings.APP_URL or 'http://localhost:5173').rstrip('/')}/reset-password#{token}"


def request_by_email(session: Session, email: str) -> tuple[str, str] | None:
    """For "Forgot your password?": the (address, link) to email, or None when there's no
    such active person or they were sent one moments ago. The caller answers the same
    either way, so the response doesn't reveal who has an account."""
    user = session.exec(select(User).where(User.email == email.lower())).first()
    if user is None or not user.is_active:
        return None
    recent = session.exec(
        select(PasswordResetToken).where(
            PasswordResetToken.user_id == user.id,
            col(PasswordResetToken.created_by_id).is_(None),
            col(PasswordResetToken.created_at) > utcnow() - EMAIL_EVERY,
        )
    ).first()
    if recent is not None:
        return None
    token, _ = create_link(session, user, EMAILED_LINK_LIFETIME)
    return user.email, reset_url(token)


def reset_password(session: Session, token: str, new_password: str) -> User:
    row = session.exec(
        select(PasswordResetToken).where(PasswordResetToken.token_hash == hash_api_token(token))
    ).first()
    if row is None or row.expires_at <= utcnow():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID)
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, INVALID)
    user.hashed_password = hash_password(new_password)
    session.add(user)
    session.exec(delete(PasswordResetToken).where(PasswordResetToken.user_id == user.id))
    end_sessions(session, user.id)  # type: ignore[arg-type]
    # a fresh start for whoever was locked out by wrong guesses
    session.exec(delete(LoginFailure).where(LoginFailure.email == user.email))
    session.commit()
    return user


def send_reset_email(to: str, url: str) -> None:
    """Runs after the response is sent. Without SMTP (developing), logs the link instead."""
    if not settings.emails_enabled:
        log.warning("Email isn't set up, so here is the password reset link for %s: %s", to, url)
        return
    msg = EmailMessage()
    msg["Subject"] = "Reset your Dealflow password"
    msg["From"] = settings.EMAILS_FROM
    msg["To"] = to
    msg.set_content(
        "Someone (hopefully you) asked to reset the password for this Dealflow account.\n\n"
        f"Choose a new password here (the link works once, for the next hour):\n{url}\n\n"
        "If it wasn't you, ignore this email; your password stays as it is.\n"
    )
    try:
        context = ssl.create_default_context()
        if settings.SMTP_STARTTLS:
            server: smtplib.SMTP = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=20)  # type: ignore[arg-type]
            server.starttls(context=context)
        else:
            server = smtplib.SMTP_SSL(
                settings.SMTP_HOST,  # type: ignore[arg-type]
                settings.SMTP_PORT,
                context=context,
                timeout=20,
            )
        with server:
            if settings.SMTP_USER:
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD or "")
            server.send_message(msg)
    except (OSError, smtplib.SMTPException):
        log.exception("Couldn't send the password reset email to %s", to)
