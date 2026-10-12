"""Alerts beyond the app (Phase 11): which notifications go by email, when, and what they say.

The rules live here; how a message leaves (email today, SMS later) lives in ``channels``.

- **Urgent** kinds are emailed straight away:
  - high risk (BR-10);
  - stop-work (BR-11);
  - heavy rain on a pour (BR-06);
  - high-severity issues;
  - anything waiting for the reader's approval.

  Stop-work emails can't be switched off.
- **Everything else** goes in one evening digest, skipped when there is nothing new.
- **What an email says:** the notification's title, a fixed sentence for its kind, and a link to the
  app. Never the notification's body. Bodies can hold a comment, a person's name, an amount or a
  line of a daily report, and the email must not carry any of them: no costs for engineers, nothing
  internal for clients, no report text leaving the server.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import get_settings
from app.core.errors import BusinessRuleError
from app.core.permissions import Role
from app.models import EmailOutbox, Notification, NotificationPreference, User
from app.schemas.analytics import NotificationPreferencesIn, NotificationPreferencesOut
from app.services import audit
from app.services.audit import RequestMeta

ALWAYS_EMAILED = frozenset({"stop_work"})
URGENT_KINDS = frozenset(
    {
        "risk_high",  # BR-10
        "stop_work",  # BR-11
        "pour_rain",  # BR-06
        "issue_high",  # a confirmed high-severity issue: the PM is alerted at once (Phase 7)
        "request_pending",  # a material request waiting for this person's approval
        "claim_submitted",  # a progress claim waiting for the PM
        "variation_for_pm",  # a variation waiting for the PM's decision
        "variation_for_client",  # a variation waiting for the client's decision
    }
)
# One fixed sentence per kind: the email's only text besides the title and the link.
SENTENCES: dict[str, str] = {
    "risk_high": (
        "A project has reached high risk. The forecast, its likely range and what is driving it "
        "are in the app."
    ),
    "stop_work": (
        "A stop-work flag has been raised. Stopped tasks take no progress until the project "
        "manager clears it."
    ),
    "pour_rain": "Heavy rain is forecast on a day a concrete pour is planned to be worked.",
    "issue_high": "A high-severity issue was confirmed in a daily report.",
    "request_pending": "A material request is waiting for your approval.",
    "claim_submitted": "A progress claim is waiting for your approval.",
    "variation_for_pm": "A variation is waiting for your decision.",
    "variation_for_client": "A variation is waiting for your decision.",
}
GENERIC_SENTENCE = "There is an update for you in SiteSense."
SETTINGS_PATH = "/settings/notifications"
# Only roles that see costs can get the weekly PDF: project managers by default, quantity surveyors by choice.
WEEKLY_ROLES = frozenset({Role.PROJECT_MANAGER.value, Role.QUANTITY_SURVEYOR.value})
WEEKLY_TIME = "Monday 07:00"


def is_urgent(kind: str) -> bool:
    return kind in URGENT_KINDS


def preferences(db: Session, user_id: uuid.UUID) -> NotificationPreference:
    """The user's stored choices, or the defaults (not saved)."""
    stored = db.get(NotificationPreference, user_id)
    if stored is not None:
        return stored
    return NotificationPreference(
        user_id=user_id, email_urgent=True, email_digest=True, weekly_report=None, updated_at=clock.utcnow()
    )


def wants_weekly_report(user: User, prefs: NotificationPreference) -> bool:
    """Only roles that see costs get the PDF. PMs by default; QSs if they opt in; anyone may opt out."""
    if user.role == Role.PROJECT_MANAGER.value:
        return prefs.weekly_report is not False
    if user.role == Role.QUANTITY_SURVEYOR.value:
        return prefs.weekly_report is True
    return False


def _link(path: str | None) -> str:
    base = get_settings().app_base_url.rstrip("/")
    return f"{base}{path or '/'}"


def _footer() -> str:
    return f"Choose which emails you get: {_link(SETTINGS_PATH)}"


def urgent_email(title: str, kind: str, link: str | None) -> tuple[str, str]:
    """(subject, body) for an urgent alert. Built only from the title, the kind and the in-app link."""
    sentence = SENTENCES.get(kind, GENERIC_SENTENCE)
    body = f"{title}\n\n{sentence}\n\nOpen it in SiteSense: {_link(link)}\n\n{_footer()}\n"
    return f"SiteSense: {title}"[:200], body


def weekly_email() -> tuple[str, str]:
    """(subject, body) for the Monday email. The figures are only in the attached PDF."""
    body = (
        "Your SiteSense weekly report is attached as a PDF.\n\n"
        f"Open the dashboard: {_link('/')}\n\n{_footer()}\n"
    )
    return "SiteSense: your weekly report", body


def queue_urgent(db: Session, user_id: uuid.UUID, kind: str, title: str, link: str | None) -> bool:
    """Queue the email for a just-created urgent notification, if the user takes urgent email."""
    if not is_urgent(kind):
        return False
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return False
    if kind not in ALWAYS_EMAILED and not preferences(db, user_id).email_urgent:
        return False
    subject, body = urgent_email(title, kind, link)
    db.add(EmailOutbox(user_id=user_id, kind="urgent", subject=subject, body=body, created_at=clock.utcnow()))
    return True


DIGEST_LIMIT = 25


def queue_digests(db: Session, now: datetime | None = None) -> int:
    """The evening digest: each user's non-urgent notifications since their last digest. Commits.

    Skipped when there is nothing new. Returns how many digests were queued.
    """
    now = now or clock.utcnow()
    queued = 0
    for user in db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.email)):
        prefs = db.get(NotificationPreference, user.id)
        if prefs is not None and not prefs.email_digest:
            continue
        # Since the last digest; the first one covers the last day only, never a backlog.
        since = (
            prefs.last_digest_at if prefs is not None and prefs.last_digest_at else now - timedelta(days=1)
        )
        query = select(Notification).where(
            Notification.user_id == user.id,
            Notification.kind.not_in(URGENT_KINDS),
            Notification.created_at > since,
            Notification.created_at <= now,
        )
        items = list(db.scalars(query.order_by(Notification.created_at.desc()).limit(DIGEST_LIMIT + 1)))
        if prefs is None:
            prefs = NotificationPreference(
                user_id=user.id, email_urgent=True, email_digest=True, weekly_report=None, updated_at=now
            )
            db.add(prefs)
        prefs.last_digest_at = now
        if not items:
            continue
        lines = [f"- {n.title}" for n in items[:DIGEST_LIMIT]]
        more = "\n(and more in the app)" if len(items) > DIGEST_LIMIT else ""
        count = len(items) if len(items) <= DIGEST_LIMIT else f"{DIGEST_LIMIT}+"
        body = (
            f"Your SiteSense updates since the last digest ({count}):\n\n"
            + "\n".join(lines)
            + more
            + f"\n\nOpen SiteSense: {_link('/')}\n\n{_footer()}\n"
        )
        db.add(EmailOutbox(user_id=user.id, kind="digest", subject="SiteSense: your daily updates", body=body,
                           created_at=now))  # fmt: skip
        queued += 1
    db.commit()
    return queued


# --- The user's choices (Settings, Notifications) --------------------------------------------------------


def preferences_out(db: Session, user: User) -> NotificationPreferencesOut:
    settings = get_settings()
    prefs = preferences(db, user.id)
    return NotificationPreferencesOut(
        email_urgent=prefs.email_urgent,
        email_digest=prefs.email_digest,
        weekly_report=wants_weekly_report(user, prefs),
        weekly_report_available=user.role in WEEKLY_ROLES,
        stop_work_always=True,
        email_configured=bool(settings.smtp_host),
        digest_time=f"{settings.digest_hour:02d}:{settings.digest_minute:02d}",
        weekly_time=WEEKLY_TIME,
    )


def update_preferences(
    db: Session, user: User, data: NotificationPreferencesIn, *, meta: RequestMeta
) -> NotificationPreferencesOut:
    """Save the user's own choices. Audited: switching off someone's alerts is worth a trail."""
    if data.weekly_report and user.role not in WEEKLY_ROLES:
        raise BusinessRuleError(
            "The weekly report holds cost figures, so only project managers and quantity surveyors "
            "can get it."
        )
    prefs = db.get(NotificationPreference, user.id)
    if prefs is None:
        prefs = NotificationPreference(
            user_id=user.id, email_urgent=True, email_digest=True, weekly_report=None
        )
        db.add(prefs)
    before = {
        "email_urgent": prefs.email_urgent,
        "email_digest": prefs.email_digest,
        "weekly": prefs.weekly_report,
    }
    prefs.email_urgent = data.email_urgent
    prefs.email_digest = data.email_digest
    if user.role in WEEKLY_ROLES and data.weekly_report is not None:
        prefs.weekly_report = data.weekly_report
    prefs.updated_at = clock.utcnow()
    after = {
        "email_urgent": prefs.email_urgent,
        "email_digest": prefs.email_digest,
        "weekly": prefs.weekly_report,
    }
    if before != after:
        audit.record(
            db,
            audit.AuditAction.NOTIFICATION_PREFERENCES_CHANGED,
            meta=meta,
            actor_id=user.id,
            target_type="user",
            target_id=user.id,
            details={"before": before, "after": after},
        )
    db.commit()
    return preferences_out(db, user)
