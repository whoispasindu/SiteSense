"""Alerts beyond the app (Phase 11): email preferences, the email outbox, and the daily briefing."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin

MAX_ATTACHMENT_BYTES = 5 * 1024 * 1024


class NotificationPreference(Base):
    """One user's email choices. No row means the defaults (both on; the weekly report by role)."""

    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # Urgent alerts by email at once. Stop-work (BR-11) is emailed even when this is off.
    email_urgent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # The evening digest of everything else (skipped when there is nothing new).
    email_digest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    # The Monday PDF: NULL means the role's default (on for project managers, off for quantity surveyors).
    weekly_report: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # The digest covers notifications after this moment.
    last_digest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EmailOutbox(UUIDPrimaryKeyMixin, Base):
    """An email waiting to go, written in the same transaction as what caused it (transactional outbox).

    A scheduled job sends pending rows and records failures, so a slow or failing mail server never
    slows a request or loses an alert. The body is built from fixed templates: never a notification's
    free text, a comment, a report or an amount.
    """

    __tablename__ = "email_outbox"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # urgent, digest, weekly_report
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="email", server_default="email")
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    attachment_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attachment: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(String(300), nullable=True)

    __table_args__ = (
        CheckConstraint("kind IN ('urgent', 'digest', 'weekly_report')", name="kind_valid"),
        CheckConstraint("channel IN ('email')", name="channel_valid"),
        CheckConstraint(
            f"attachment IS NULL OR length(attachment) <= {MAX_ATTACHMENT_BYTES}", name="attachment_size"
        ),
        CheckConstraint("(attachment IS NULL) = (attachment_name IS NULL)", name="attachment_named"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
    )


class Briefing(UUIDPrimaryKeyMixin, Base):
    """A user's daily briefing, cached for the day and rebuilt when its facts change."""

    __tablename__ = "briefings"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    briefing_date: Mapped[date] = mapped_column(Date, nullable=False)
    facts_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)  # "ai" or "rules"
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bullets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("user_id", "briefing_date", name="uq_briefings_user_date"),
        CheckConstraint("source IN ('ai', 'rules')", name="source_valid"),
        CheckConstraint("(source = 'ai') = (model IS NOT NULL)", name="model_when_ai"),
    )
