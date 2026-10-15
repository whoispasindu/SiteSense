"""Daily site reports, their photos and the task progress they record.

One report per project per site day (TC-03). The engineer who wrote it may correct it on the
day they submitted it; after that it is part of the record. Photos are stored outside the
database (``app.integrations.storage``); the table keeps only the key and verified metadata.
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.schedule import PERCENT
from app.models.user import User

TEMPERATURE = Numeric(4, 1)
RAINFALL = Numeric(6, 1)


class DailyReport(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "daily_reports"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    # Users are deactivated, never deleted, so the author always resolves.
    author_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    report_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Weather on the day: pre-filled from the forecast, editable by the engineer.
    weather_summary: Mapped[str | None] = mapped_column(String(60), nullable=True)
    temp_max_c: Mapped[Decimal | None] = mapped_column(TEMPERATURE, nullable=True)
    temp_min_c: Mapped[Decimal | None] = mapped_column(TEMPERATURE, nullable=True)
    rain_mm: Mapped[Decimal | None] = mapped_column(RAINFALL, nullable=True)
    # "forecast": accepted as pre-filled; "manual": typed or changed by the engineer.
    weather_source: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")

    crew_count: Mapped[int] = mapped_column(Integer, nullable=False)
    work_done: Mapped[str] = mapped_column(Text, nullable=False)
    problems: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    author: Mapped[User] = relationship(lazy="joined")
    photos: Mapped[list["ReportPhoto"]] = relationship(
        back_populates="report", order_by="ReportPhoto.position", cascade="all, delete-orphan"
    )
    progress: Mapped[list["ReportProgress"]] = relationship(
        back_populates="report", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("project_id", "report_date", name="uq_daily_reports_project_date"),
        CheckConstraint("crew_count >= 0 AND crew_count <= 5000", name="crew_count_range"),
        CheckConstraint("weather_source IN ('forecast', 'manual')", name="weather_source_values"),
        CheckConstraint("rain_mm IS NULL OR rain_mm >= 0", name="rain_not_negative"),
    )


class ReportPhoto(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "report_photos"

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # Server-generated, never derived from the client's file name.
    storage_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    content_type: Mapped[str] = mapped_column(String(24), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    width: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    height: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    caption: Mapped[str | None] = mapped_column(String(200), nullable=True)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Phase 12: private by default; the project manager shares chosen photos with the client.
    shared_with_client: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    shared_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    shared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    report: Mapped[DailyReport] = relationship(back_populates="photos")

    __table_args__ = (
        CheckConstraint("size_bytes > 0", name="size_positive"),
        CheckConstraint("shared_with_client = (shared_at IS NOT NULL)", name="shared_when_dated"),
    )


class ReportProgress(UUIDPrimaryKeyMixin, Base):
    """A task's percent complete as reported in a daily report (before and after)."""

    __tablename__ = "report_progress"

    report_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("daily_reports.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Kept if the task is later deleted: the report is a record of what was said on the day.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_name: Mapped[str] = mapped_column(String(160), nullable=False)
    percent_before: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    percent_after: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)

    report: Mapped[DailyReport] = relationship(back_populates="progress")

    __table_args__ = (
        CheckConstraint("percent_after >= 0 AND percent_after <= 100", name="percent_after_range"),
    )


class WeatherForecast(UUIDPrimaryKeyMixin, Base):
    """Cached daily forecast per site, so reports and dashboards work when the API is down (TC-08)."""

    __tablename__ = "weather_forecasts"

    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id", ondelete="CASCADE"), nullable=False)
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    weather_code: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    summary: Mapped[str] = mapped_column(String(60), nullable=False)
    temp_max_c: Mapped[Decimal | None] = mapped_column(TEMPERATURE, nullable=True)
    temp_min_c: Mapped[Decimal | None] = mapped_column(TEMPERATURE, nullable=True)
    rain_mm: Mapped[Decimal | None] = mapped_column(RAINFALL, nullable=True)
    rain_probability: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (UniqueConstraint("site_id", "forecast_date", name="uq_weather_forecasts_site_date"),)


class Notification(UUIDPrimaryKeyMixin, Base):
    """In-app notification for one user. Later phases add their own ``kind`` values."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    # In-app path only ("/..." but not "//host"), never an external URL.
    link: Mapped[str | None] = mapped_column(String(200), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Makes scheduled notifications idempotent: the same reminder is never sent twice.
    dedupe_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notifications_user_dedupe_key"),
        # The bell and the notifications page: one person's newest first (Phase 13).
        Index("ix_notifications_user_created", "user_id", "created_at"),
        CheckConstraint("link IS NULL OR (link LIKE '/%' AND link NOT LIKE '//%')", name="link_is_internal"),
    )
