"""The client portal (Phase 12): the handover date the project manager publishes to the client."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class HandoverPublication(UUIDPrimaryKeyMixin, Base):
    """One publication of the client-facing handover date, or a review confirming it unchanged.

    The latest row is what the client sees; earlier "published" rows are the history they see too.
    "confirmed" rows record a review with no change: they reset the 30-day reminder and are shown only
    to the contractor. Append-only: a change is a new row, never an edit.
    """

    __tablename__ = "handover_publications"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # published | confirmed
    handover_date: Mapped[date] = mapped_column(Date, nullable=False)
    # Written for the client: why the date is what it is.
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    # What the programme forecast at the time, for the record (not shown to the client).
    programme_forecast: Mapped[date | None] = mapped_column(Date, nullable=True)
    published_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        CheckConstraint("kind IN ('published', 'confirmed')", name="kind_valid"),
        CheckConstraint("length(reason) BETWEEN 3 AND 300", name="reason_length"),
        Index("ix_handover_publications_project_at", "project_id", "published_at"),
    )
