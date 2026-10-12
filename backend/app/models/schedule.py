"""Programme tasks, their dependencies, the company's holidays and the daily history of progress.

Phase 9: tasks are linked finish-to-start (``task_dependencies``); the critical path and forecast are
calculated on each project's working calendar (``app.rules.calendar``, ``app.rules.schedule``), so
nothing about them is stored except the inputs.
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
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core import clock
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
    # BR-06: a concrete pour is flagged when heavy rain is forecast on a working day of its window.
    is_concrete_pour: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    progress_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set when progress first goes above 0% and when it reaches 100%: the forecast's actual dates.
    actual_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    actual_finish: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Phase 12: shown to the client as a milestone, under an optional client-friendly name.
    client_milestone: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    milestone_name: Mapped[str | None] = mapped_column(String(80), nullable=True)

    __table_args__ = (
        CheckConstraint("planned_end >= planned_start", name="dates_in_order"),
        CheckConstraint("weight > 0 AND weight <= 100", name="weight_range"),
        CheckConstraint("percent_complete >= 0 AND percent_complete <= 100", name="percent_complete_range"),
        CheckConstraint("(percent_complete > 0) = (actual_start IS NOT NULL)", name="started_when_progress"),
        CheckConstraint("(percent_complete = 100) = (actual_finish IS NOT NULL)", name="finished_when_done"),
        CheckConstraint(
            "actual_finish IS NULL OR actual_finish >= actual_start", name="actual_dates_in_order"
        ),
        CheckConstraint("milestone_name IS NULL OR client_milestone", name="milestone_name_when_milestone"),
        Index(
            "uq_tasks_project_code", "project_id", "code", unique=True, postgresql_where="code IS NOT NULL"
        ),
    )


@event.listens_for(Task, "before_insert")
@event.listens_for(Task, "before_update")
def _fill_actual_dates(_mapper: object, _connection: object, task: Task) -> None:
    """Keep the actual dates in step with progress whatever wrote it.

    The services set them precisely (``schedule_service.apply_progress``); this fills only what is
    missing, so a task saved with progress some other way (an import, a fixture) is still valid:
    started on its planned start (or today, if that is later), finished today.
    """
    today = clock.site_today()
    if task.percent_complete is None or task.percent_complete <= 0:
        task.actual_start = task.actual_finish = None
        return
    if task.actual_start is None:
        task.actual_start = min(task.planned_start, today)
    if task.percent_complete >= 100:
        if task.actual_finish is None:
            task.actual_finish = max(task.actual_start, today)
    else:
        task.actual_finish = None


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


class TaskDependency(UUIDPrimaryKeyMixin, Base):
    """Finish-to-start: the successor starts the working day after the predecessor finishes, plus lag."""

    __tablename__ = "task_dependencies"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    predecessor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    successor_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("predecessor_id", "successor_id", name="uq_task_dependencies_pair"),
        CheckConstraint("predecessor_id <> successor_id", name="not_self"),
        CheckConstraint("lag_days BETWEEN 0 AND 365", name="lag_range"),
        Index("ix_task_dependencies_successor", "successor_id"),
    )


class Holiday(UUIDPrimaryKeyMixin, Base):
    """A company-wide day off (Poya days, public holidays). Kept by the Company Admin."""

    __tablename__ = "holidays"

    holiday_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
