"""Projects, their bill of quantities (BOQ) and the internal cost budget per BOQ section.

Money is NUMERIC, never float. The BOQ carries *contract* rates (what the client pays); the
budget line carries the contractor's *cost* budget for the same section, so the difference is
the expected margin. Committed and spent cost are added to budget lines in Phase 5.
"""

import uuid
from datetime import date
from decimal import Decimal
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.user import Site

MONEY = Numeric(16, 2)
QUANTITY = Numeric(14, 3)
RATE = Numeric(14, 2)


class ProjectStatus(StrEnum):
    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProjectType(StrEnum):
    RESIDENTIAL = "residential"
    COMMERCIAL = "commercial"
    MIXED_USE = "mixed_use"
    INDUSTRIAL = "industrial"
    INSTITUTIONAL = "institutional"


class Project(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "projects"

    code: Mapped[str] = mapped_column(String(24), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    site_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sites.id"), nullable=False, index=True)
    client_name: Mapped[str] = mapped_column(String(160), nullable=False)
    project_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=ProjectStatus.PLANNING.value)
    contract_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    planned_end: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    site: Mapped[Site] = relationship(lazy="joined")
    sections: Mapped[list["BoqSection"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="BoqSection.position"
    )

    __table_args__ = (
        CheckConstraint("contract_value > 0", name="contract_value_positive"),
        CheckConstraint("planned_end >= start_date", name="dates_in_order"),
        CheckConstraint(
            "status IN ('planning', 'active', 'on_hold', 'completed', 'cancelled')", name="status_valid"
        ),
        CheckConstraint(
            "project_type IN ('residential', 'commercial', 'mixed_use', 'industrial', 'institutional')",
            name="project_type_valid",
        ),
    )


class BoqSection(UUIDPrimaryKeyMixin, Base):
    """A BOQ section such as "B - Substructure". One budget line per section."""

    __tablename__ = "boq_sections"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    project: Mapped[Project] = relationship(back_populates="sections")
    items: Mapped[list["BoqItem"]] = relationship(
        back_populates="section", cascade="all, delete-orphan", order_by="BoqItem.position"
    )
    budget_line: Mapped["BudgetLine"] = relationship(
        back_populates="section", cascade="all, delete-orphan", uselist=False
    )

    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_boq_sections_project_code"),)


class BoqItem(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "boq_items"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boq_sections.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_code: Mapped[str] = mapped_column(String(24), nullable=False)
    description: Mapped[str] = mapped_column(String(500), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    rate: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    # quantity x rate, rounded to cents once at import so every total agrees.
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    section: Mapped[BoqSection] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("project_id", "item_code", name="uq_boq_items_project_item_code"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("rate >= 0", name="rate_non_negative"),
        Index("ix_boq_items_project_id", "project_id"),
    )


class BudgetLine(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """The contractor's cost budget for one BOQ section."""

    __tablename__ = "budget_lines"

    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    section_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boq_sections.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    budget_amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    section: Mapped[BoqSection] = relationship(back_populates="budget_line")

    __table_args__ = (CheckConstraint("budget_amount >= 0", name="budget_amount_non_negative"),)
