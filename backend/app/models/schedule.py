"""Programme tasks and the daily history of actual progress.

Dependencies and the critical path arrive in Phase 9; ``is_critical`` is set by hand until then.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

PERCENT = Numeric(5, 2)


class Task(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tasks"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Optional link to the BOQ section the task delivers (used for weight hints and, later, costs).
    boq_section_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("boq_sections.id", ondelete="SET NULL"), nullable=True
    )
    code: Mapped[str | None] = mapped_column(String(16), nullable=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    planned_start: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end: Mapped[date] = mapped_column(Date, nullable=False)
    # Share of the contract, in percent.
    weight: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    percent_complete: Mapped[Decimal] = mapped_column(PERCENT, nullable=False, default=Decimal(0))
    is_critical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint("planned_end >= planned_start", name="dates_in_order"),
        CheckConstraint("weight > 0 AND weight <= 100", name="weight_range"),
        CheckConstraint("percent_complete >= 0 AND percent_complete <= 100", name="percent_complete_range"),
        Index(
            "uq_tasks_project_code", "project_id", "code", unique=True, postgresql_where="code IS NOT NULL"
        ),
    )


class ProgressSnapshot(UUIDPrimaryKeyMixin, Base):
    """The project's actual progress at the end of a day: the history behind the S-curve."""

    __tablename__ = "progress_snapshots"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_percent: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "snapshot_date", name="uq_progress_snapshots_project_date"),
        CheckConstraint("actual_percent >= 0 AND actual_percent <= 100", name="actual_percent_range"),
    )
