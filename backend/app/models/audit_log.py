import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPrimaryKeyMixin


class AuditLog(UUIDPrimaryKeyMixin, Base):
    """Append-only record of security-relevant events: who did what, to what, and when.

    The application database role may INSERT and SELECT here but not UPDATE or DELETE
    (enforced by grants in the migration), so a compromised API cannot rewrite history.
    """

    __tablename__ = "audit_logs"

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, server_default="{}", nullable=False)

    __table_args__ = (
        Index("ix_audit_logs_occurred_at", "occurred_at"),
        Index("ix_audit_logs_action_occurred_at", "action", "occurred_at"),
    )
