"""Risk scores: one row per project per day, the history behind the dashboard ranking (Phase 6)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class RiskScore(UUIDPrimaryKeyMixin, Base):
    """The model's forecast for a project on a day. Re-scoring the same day replaces the row."""

    __tablename__ = "risk_scores"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    score_date: Mapped[date] = mapped_column(Date, nullable=False)
    score: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    level: Mapped[str] = mapped_column(String(8), nullable=False)
    delay_days: Mapped[Decimal] = mapped_column(Numeric(7, 1), nullable=False)
    overrun_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False)
    # Likely ranges arrive with risk model v2 (Phase 10).
    ranges: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    drivers: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # The inputs the model saw and what was missing: every forecast shows the data it used.
    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model_version: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        UniqueConstraint("project_id", "score_date", name="uq_risk_scores_project_date"),
        CheckConstraint("score >= 0 AND score <= 100", name="score_range"),
        CheckConstraint("level IN ('low', 'medium', 'high')", name="level_values"),
    )
