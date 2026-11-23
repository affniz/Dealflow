"""Sending email over SMTP, when it's set up (settings.emails_enabled)."""

import logging
import smtplib
import ssl
from email.message import EmailMessage

from app.core.config import settings

log = logging.getLogger(__name__)


def send_email(to: str | list[str], subject: str, body: str) -> bool:
    """Send a plain-text email; False (and logged) if it couldn't be sent. Several
    recipients each see only their own address."""
    recipients = [to] if isinstance(to, str) else to
    if not settings.emails_enabled or not recipients:
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = settings.EMAILS_FROM
    msg["To"] = recipients[0] if len(recipients) == 1 else settings.EMAILS_FROM
    msg.set_content(body)
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
            server.send_message(msg, to_addrs=recipients)
    except (OSError, smtplib.SMTPException):
        log.exception("Couldn't send the email %r", subject, extra={"recipients": len(recipients)})
        return False
    return True
