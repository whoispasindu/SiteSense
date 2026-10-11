"""Progress claims and variation orders: the contract side of a project (Phase 8).

A progress claim certifies a percentage complete per BOQ section; its amount is calculated (BR-08,
``app.rules.claims``) and the figures are stored as they were when the claim was made. A variation
order changes the contract: the QS prices it, it is approved by the PM or the client (BR-09,
``app.rules.variations``), and only then are the contract value, budget line and programme changed.
Every step of a variation is kept in ``variation_events``.
"""

import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

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
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, UUIDPrimaryKeyMixin
from app.models.project import MONEY, QUANTITY, BoqSection
from app.models.schedule import PERCENT
from app.models.user import User
from app.rules.variations import VariationStatus

OVERALL_PERCENT = Numeric(9, 6)  # value-weighted certified progress, kept precise


def _values(enum: type[StrEnum]) -> str:
    return ", ".join(f"'{e.value}'" for e in enum)


class ClaimStatus(StrEnum):
    SUBMITTED = "submitted"  # by the QS, waiting for the PM
    APPROVED = "approved"  # shown to the client; counts as a previous claim
    RETURNED = "returned"  # sent back by the PM; the QS makes a new claim
    PAID = "paid"


class ProgressClaim(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "progress_claims"

    number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    # The figures when the claim was made (BR-08). amount = certified_value - retention - previous.
    contract_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    certified_pct: Mapped[Decimal] = mapped_column(OVERALL_PERCENT, nullable=False)
    certified_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    retention: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    previous_claims: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    paid_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    paid_recorded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)

    submitter: Mapped[User] = relationship(lazy="joined", foreign_keys=[submitted_by])
    decider: Mapped[User | None] = relationship(lazy="joined", foreign_keys=[decided_by])
    lines: Mapped[list["ProgressClaimLine"]] = relationship(
        back_populates="claim", cascade="all, delete-orphan", order_by="ProgressClaimLine.position"
    )

    __table_args__ = (
        CheckConstraint(f"status IN ({_values(ClaimStatus)})", name="status_values"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint("retention >= 0 AND previous_claims >= 0", name="retention_previous_non_negative"),
        CheckConstraint("certified_pct BETWEEN 0 AND 100", name="certified_pct_range"),
        # BR-08 holds in the stored figures, whatever wrote them.
        CheckConstraint("amount + retention + previous_claims = certified_value", name="br08_figures_add_up"),
        CheckConstraint("certified_value <= contract_value", name="certified_within_contract"),
        CheckConstraint("(status = 'paid') = (paid_on IS NOT NULL)", name="paid_on_when_paid"),
        CheckConstraint("(status = 'submitted') = (decided_at IS NULL)", name="decided_unless_submitted"),
        # One claim waits for the PM at a time, so "previous claims" is never ambiguous.
        Index(
            "uq_progress_claims_one_submitted",
            "project_id",
            unique=True,
            postgresql_where=text("status = 'submitted'"),
        ),
        Index("ix_progress_claims_project", "project_id", "submitted_at"),
    )


class ProgressClaimLine(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "progress_claim_lines"

    claim_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("progress_claims.id", ondelete="CASCADE"), nullable=False
    )
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boq_sections.id"), nullable=False)
    section_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    certified_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    previous_pct: Mapped[Decimal] = mapped_column(PERCENT, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    claim: Mapped[ProgressClaim] = relationship(back_populates="lines")
    section: Mapped[BoqSection] = relationship(lazy="joined")

    __table_args__ = (
        UniqueConstraint("claim_id", "section_id", name="uq_progress_claim_lines_section"),
        CheckConstraint("certified_pct BETWEEN 0 AND 100", name="certified_pct_range"),
        CheckConstraint("previous_pct BETWEEN 0 AND certified_pct", name="not_below_previous"),
        CheckConstraint("section_value >= 0", name="section_value_non_negative"),
    )


class VariationOrder(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "variation_orders"

    number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    section_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("boq_sections.id"), nullable=False)
    # Extra quantity on one BOQ item (it raises that item's BR-02 allowance once approved).
    boq_item_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("boq_items.id"), nullable=True)
    quantity_change: Mapped[Decimal | None] = mapped_column(QUANTITY, nullable=True)
    # The programme task the time impact extends.
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tasks.id", ondelete="SET NULL"), nullable=True
    )
    time_impact_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # Set by the QS: the change to the contract value (client-facing) and to the section's cost budget.
    contract_change: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    budget_change: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    approver: Mapped[str | None] = mapped_column(String(8), nullable=True)  # pm | client, once priced
    limit_applied: Mapped[Decimal | None] = mapped_column(MONEY, nullable=True)  # BR-09 limit at routing
    raised_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    raised_by_role: Mapped[str] = mapped_column(String(4), nullable=False)
    raised_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    priced_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    priced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When it first went to the client. From then on the client always sees it, and a revision goes
    # back to the client rather than to the PM.
    sent_to_client_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    raiser: Mapped[User] = relationship(lazy="joined", foreign_keys=[raised_by])
    section: Mapped[BoqSection] = relationship(lazy="joined")
    events: Mapped[list["VariationEvent"]] = relationship(
        back_populates="variation", cascade="all, delete-orphan", order_by="VariationEvent.created_at"
    )

    __table_args__ = (
        CheckConstraint(f"status IN ({_values(VariationStatus)})", name="status_values"),
        CheckConstraint("approver IS NULL OR approver IN ('pm', 'client')", name="approver_values"),
        CheckConstraint("raised_by_role IN ('pm', 'qs')", name="raised_by_role_values"),
        CheckConstraint("time_impact_days BETWEEN 0 AND 3650", name="time_impact_range"),
        CheckConstraint("(boq_item_id IS NULL) = (quantity_change IS NULL)", name="item_with_quantity"),
        CheckConstraint("quantity_change IS NULL OR quantity_change > 0", name="quantity_change_positive"),
        CheckConstraint("(contract_change IS NULL) = (budget_change IS NULL)", name="priced_together"),
        CheckConstraint("(contract_change IS NULL) = (priced_at IS NULL)", name="priced_at_when_priced"),
        # Nothing waits for an approver, or is approved, without a price (the QS prices every variation).
        CheckConstraint(
            "status NOT IN ('awaiting_pm', 'awaiting_client', 'approved') OR "
            "(contract_change IS NOT NULL AND approver IS NOT NULL AND limit_applied IS NOT NULL)",
            name="priced_before_approval",
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'rejected') OR decided_at IS NOT NULL", name="decided_when_closed"
        ),
        Index("ix_variation_orders_project_status", "project_id", "status"),
        Index("ix_variation_orders_item_status", "boq_item_id", "status"),
    )


class VariationEvent(UUIDPrimaryKeyMixin, Base):
    """One step in a variation's life: raised, priced, revised, approved, queried, rejected, withdrawn."""

    __tablename__ = "variation_events"

    variation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("variation_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Steps the client may see (their own decisions, and the variation reaching them). Internal steps,
    # such as pricing against the cost budget, are not shown in the client's view.
    client_visible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    variation: Mapped[VariationOrder] = relationship(back_populates="events")
    actor: Mapped[User] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint(
            "action IN ('raised', 'priced', 'revised', 'approved', 'queried', 'rejected', 'withdrawn')",
            name="action_values",
        ),
    )
