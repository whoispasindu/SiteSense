"""Issues tagged in daily reports and the follow-up actions they create (Phase 7).

One row per tagged sentence from a report's "Problems" text. The AI suggests the category and
severity; the report's author confirms, edits or removes each suggestion, and may add tags of their
own. The AI's original suggestion is kept beside the confirmed values, so the share of tags accepted
without editing can be measured.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class IssueCategory(StrEnum):
    MATERIAL_DELAY = "material_delay"
    LABOUR = "labour"
    WEATHER = "weather"
    EQUIPMENT = "equipment"
    SAFETY = "safety"
    DESIGN = "design"
    QUALITY = "quality"
    OTHER = "other"


class IssueSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class IssueStatus(StrEnum):
    SUGGESTED = "suggested"  # from the AI, waiting for the author
    CONFIRMED = "confirmed"
    REMOVED = "removed"  # suggested, then removed by the author


class ActionKind(StrEnum):
    MATERIAL_REQUEST = "material_request"  # a pre-filled request for a material delay
    PM_ALERT = "pm_alert"  # high severity: the site's project managers are told
    STOP_WORK = "stop_work"  # safety: open until the project manager clears it (BR-11)


class ActionStatus(StrEnum):
    OPEN = "open"
    DONE = "done"
    DISMISSED = "dismissed"


def _values(enum: type[StrEnum]) -> str:
    return ", ".join(f"'{e.value}'" for e in enum)


class ReportIssue(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "report_issues"

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # The sentence the tag is about, with people's names replaced by [PERSON].
    snippet: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False)  # "ai" or "manual"
    ai_category: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ai_severity: Mapped[str | None] = mapped_column(String(8), nullable=True)
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3), nullable=True)
    low_confidence: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    model_version: Mapped[str | None] = mapped_column(String(16), nullable=True)
    position: Mapped[int] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(f"category IN ({_values(IssueCategory)})", name="category_values"),
        CheckConstraint(f"severity IN ({_values(IssueSeverity)})", name="severity_values"),
        CheckConstraint(f"status IN ({_values(IssueStatus)})", name="status_values"),
        CheckConstraint("source IN ('ai', 'manual')", name="source_values"),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)", name="confidence_range"
        ),
        CheckConstraint("length(snippet) BETWEEN 1 AND 500", name="snippet_length"),
        Index("ix_report_issues_report", "report_id", "position"),
        Index("ix_report_issues_project_status", "project_id", "status", "confirmed_at"),
    )


class ReportAction(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "report_actions"

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    summary: Mapped[str] = mapped_column(String(500), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The material request raised from a material_request action.
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("material_requests.id", ondelete="SET NULL"), nullable=True
    )

    __table_args__ = (
        CheckConstraint(f"kind IN ({_values(ActionKind)})", name="kind_values"),
        CheckConstraint(f"status IN ({_values(ActionStatus)})", name="status_values"),
        # A PM alert is sent at once, so it is recorded as done when it is created.
        CheckConstraint("(status = 'open') = (closed_at IS NULL)", name="closed_when_not_open"),
        Index("ix_report_actions_project_open", "project_id", "kind", "status"),
        Index("ix_report_actions_report", "report_id"),
    )
