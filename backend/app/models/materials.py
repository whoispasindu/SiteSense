"""Material requests, their approval history, suppliers, purchase orders and deliveries.

Workflow B: a request is raised against a BOQ item, checked by the QS, approved by the QS or
(above the BR-01 limit) the project manager, ordered on a purchase order and delivered. Committed
and spent cost are derived from purchase-order lines and deliveries, so the budget can never drift
from the documents behind it.
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
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.project import MONEY, QUANTITY, RATE, BoqItem, Project
from app.models.user import User


class RequestStatus(StrEnum):
    REQUESTED = "requested"  # waiting for the QS check
    PM_APPROVAL = "pm_approval"  # above the BR-01 limit: waiting for the project manager
    APPROVED = "approved"  # ready for a purchase order
    ORDERED = "ordered"
    DELIVERED = "delivered"
    REJECTED = "rejected"
    CHANGE_REQUESTED = "change_requested"
    CANCELLED = "cancelled"


REQUEST_STATUSES = tuple(s.value for s in RequestStatus)


class MaterialRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "material_requests"

    # Human reference, e.g. "MR-0042"; unique per company.
    number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # RESTRICT: a BOQ item with requests against it cannot be deleted (or re-imported away).
    boq_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("boq_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    # The requester's expected unit price (cost), checked against the budget line (BR-01).
    unit_price: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    needed_by: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default=RequestStatus.REQUESTED.value)
    # Set by the routing rule (BR-01) when the request is submitted: "qs" or "pm".
    approval_level: Mapped[str] = mapped_column(String(4), nullable=False)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    project: Mapped[Project] = relationship(lazy="joined")
    boq_item: Mapped[BoqItem] = relationship(lazy="joined")
    requester: Mapped[User] = relationship(lazy="joined", foreign_keys=[requested_by])
    approvals: Mapped[list["Approval"]] = relationship(
        back_populates="request", order_by="Approval.created_at", cascade="all, delete-orphan"
    )
    po_line: Mapped["PurchaseOrderLine | None"] = relationship(back_populates="request", uselist=False)

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
        CheckConstraint(f"status IN {REQUEST_STATUSES}", name="status_valid"),
        CheckConstraint("approval_level IN ('qs', 'pm')", name="approval_level_valid"),
        Index("ix_material_requests_status", "status"),
    )


class Approval(UUIDPrimaryKeyMixin, Base):
    """One step in a request's history: submitted, approved, rejected, change requested, ordered..."""

    __tablename__ = "approvals"

    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_requests.id", ondelete="CASCADE"), nullable=False, index=True
    )
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    # submit, resubmit, approve, reject, request_change, cancel, order, deliver
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    request: Mapped[MaterialRequest] = relationship(back_populates="approvals")
    actor: Mapped[User] = relationship(lazy="joined")


class Supplier(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    contact_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), nullable=True)
    # Free text such as "cement, aggregates": used for filtering and, later, the supplier model.
    categories: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")


class PurchaseOrderStatus(StrEnum):
    ISSUED = "issued"
    PART_DELIVERED = "part_delivered"
    DELIVERED = "delivered"


class PurchaseOrder(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "purchase_orders"

    number: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    supplier_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("suppliers.id"), nullable=False, index=True)
    issued_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expected_delivery: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=PurchaseOrderStatus.ISSUED.value)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(lazy="joined")
    supplier: Mapped[Supplier] = relationship(lazy="joined")
    issuer: Mapped[User] = relationship(lazy="joined", foreign_keys=[issued_by])
    lines: Mapped[list["PurchaseOrderLine"]] = relationship(
        back_populates="purchase_order", cascade="all, delete-orphan", order_by="PurchaseOrderLine.position"
    )

    __table_args__ = (
        CheckConstraint("status IN ('issued', 'part_delivered', 'delivered')", name="status_valid"),
    )


class PurchaseOrderLine(UUIDPrimaryKeyMixin, Base):
    """One approved request on a purchase order. A request is ordered at most once."""

    __tablename__ = "purchase_order_lines"

    purchase_order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("material_requests.id"), nullable=False, unique=True
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    # The agreed price: never above the approved request price (no bypass of BR-01).
    unit_price: Mapped[Decimal] = mapped_column(RATE, nullable=False)
    amount: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)

    purchase_order: Mapped[PurchaseOrder] = relationship(back_populates="lines")
    request: Mapped[MaterialRequest] = relationship(back_populates="po_line", lazy="joined")
    deliveries: Mapped[list["Delivery"]] = relationship(
        back_populates="line", order_by="Delivery.delivered_on", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price > 0", name="unit_price_positive"),
    )


class Delivery(UUIDPrimaryKeyMixin, Base):
    __tablename__ = "deliveries"

    line_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("purchase_order_lines.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    delivered_on: Mapped[date] = mapped_column(Date, nullable=False)
    received_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    line: Mapped[PurchaseOrderLine] = relationship(back_populates="deliveries")

    __table_args__ = (CheckConstraint("quantity > 0", name="quantity_positive"),)


class DocumentCounter(Base):
    """Gap-free running numbers for documents (MR-0001, PO-0001), taken under a row lock."""

    __tablename__ = "document_counters"

    kind: Mapped[str] = mapped_column(String(8), primary_key=True)
    value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
