"""Sending email over SMTP (Phase 11). The only module that talks to a mail server.

What it sends is built elsewhere from fixed templates (``app.services.alerts``) and the weekly PDF:
titles, fixed sentences, links into the app, and for project managers and quantity surveyors the
report attachment. Never report text. TLS is required in production (``Settings``).
"""

from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from app.core.config import Settings

TIMEOUT_SECONDS = 15


@dataclass(frozen=True, slots=True)
class OutboundEmail:
    to: str
    subject: str
    body: str
    attachment_name: str | None = None
    attachment: bytes | None = None


def configured(settings: Settings) -> bool:
    """Whether emails are really sent. In demo mode they never are: the demo addresses are not real
    mailboxes, so every email is written to the log instead."""
    return bool(settings.smtp_host) and not settings.demo_mode


def build(settings: Settings, email: OutboundEmail) -> EmailMessage:
    message = EmailMessage()
    message["From"] = settings.email_from
    message["To"] = email.to
    message["Subject"] = email.subject.replace("\r", " ").replace("\n", " ")  # no header injection
    message.set_content(email.body)
    if email.attachment is not None and email.attachment_name:
        message.add_attachment(
            email.attachment, maintype="application", subtype="pdf", filename=email.attachment_name
        )
    return message


def send(settings: Settings, email: OutboundEmail) -> None:
    """Deliver one email. Raises on failure; the caller records it and retries later."""
    host = settings.smtp_host
    if not host:
        raise RuntimeError("SMTP is not configured")
    message = build(settings, email)
    password = settings.smtp_password.get_secret_value() if settings.smtp_password else None
    if settings.smtp_security == "ssl":
        with smtplib.SMTP_SSL(
            host, settings.smtp_port, timeout=TIMEOUT_SECONDS, context=ssl.create_default_context()
        ) as smtp:
            if settings.smtp_username and password:
                smtp.login(settings.smtp_username, password)
            smtp.send_message(message)
        return
    with smtplib.SMTP(host, settings.smtp_port, timeout=TIMEOUT_SECONDS) as smtp:
        if settings.smtp_security == "starttls":
            smtp.starttls(context=ssl.create_default_context())
        if settings.smtp_username and password:
            smtp.login(settings.smtp_username, password)
        smtp.send_message(message)
