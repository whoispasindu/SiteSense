"""How alerts leave the app (Phase 11): one interface, one channel today (email).

The alert rules (``alerts``) decide what goes to whom and when; a channel only delivers. An SMS
channel can be added here later (a class with ``name`` and ``deliver``) without touching the rules.

``send_pending`` is the outbox sender, run by the scheduler every minute: it takes pending rows,
delivers them, and records each failure for a later retry, up to ``MAX_ATTEMPTS``.
"""

from __future__ import annotations

from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.integrations import email as email_client
from app.models import EmailOutbox, User

log = get_logger(__name__)

MAX_ATTEMPTS = 5
BATCH = 50


class Channel(Protocol):
    name: str

    def deliver(self, user: User, item: EmailOutbox) -> None:
        """Send one message, or raise."""


class EmailChannel:
    name = "email"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def deliver(self, user: User, item: EmailOutbox) -> None:
        if not email_client.configured(self.settings):
            # No SMTP settings: the email is written to the log instead (development, or not set up).
            log.info(
                "email_logged_not_sent",
                user_id=str(user.id),
                kind=item.kind,
                subject=item.subject,
                body=item.body,
                attachment=item.attachment_name,
            )
            return
        email_client.send(
            self.settings,
            email_client.OutboundEmail(
                to=user.email,
                subject=item.subject,
                body=item.body,
                attachment_name=item.attachment_name,
                attachment=item.attachment,
            ),
        )


def channels(settings: Settings | None = None) -> dict[str, Channel]:
    settings = settings or get_settings()
    return {"email": EmailChannel(settings)}


def send_pending(db: Session, settings: Settings | None = None) -> tuple[int, int]:
    """Deliver pending outbox rows. Returns (sent, failed). Commits after each row."""
    available = channels(settings)
    sent = failed = 0
    rows = db.scalars(
        select(EmailOutbox)
        .where(EmailOutbox.sent_at.is_(None), EmailOutbox.attempts < MAX_ATTEMPTS)
        .order_by(EmailOutbox.created_at)
        .limit(BATCH)
        .with_for_update(skip_locked=True)
    ).all()
    for row in rows:
        user = db.get(User, row.user_id)
        if user is None or not user.is_active:
            row.attempts = MAX_ATTEMPTS
            row.last_error = "recipient inactive"
            db.commit()
            continue
        try:
            available[row.channel].deliver(user, row)
        except Exception as exc:  # recorded and retried; the alert stays in the app either way
            row.attempts += 1
            row.last_error = f"{type(exc).__name__}"[:300]
            failed += 1
            log.warning(
                "email_failed", outbox_id=str(row.id), attempts=row.attempts, error=type(exc).__name__
            )
        else:
            row.sent_at = clock.utcnow()
            row.attempts += 1
            sent += 1
        db.commit()
    return sent, failed
