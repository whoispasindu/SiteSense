import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.project import Project

user_site_assignments = Table(
    "user_site_assignments",
    Base.metadata,
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("site_id", ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("assigned_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)

# Phase 12: which projects a client account may see. Clients reach a project only through this link,
# never through its site, so two clients on one site never see each other's projects.
project_clients = Table(
    "project_clients",
    Base.metadata,
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
    Column("user_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True, index=True),
    Column("assigned_at", DateTime(timezone=True), server_default=func.now(), nullable=False),
)


class RoleRecord(Base):
    """Lookup table for the six roles. Permissions live in code (app.core.permissions)."""

    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class Site(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A construction site. Each project (Phase 2) runs on one site."""

    __tablename__ = "sites"

    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    location: Mapped[str] = mapped_column(String(120), nullable=False)
    # Used by the weather integration in Phase 4.
    latitude: Mapped[float | None] = mapped_column(nullable=True)
    longitude: Mapped[float | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)

    __table_args__ = (
        CheckConstraint("latitude IS NULL OR latitude BETWEEN -90 AND 90", name="latitude_range"),
        CheckConstraint("longitude IS NULL OR longitude BETWEEN -180 AND 180", name="longitude_range"),
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    # Stored lower-cased; uniqueness is therefore case-insensitive.
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(ForeignKey("roles.code"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true", nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="true", nullable=False
    )
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    # Phase 13: two-step sign-in. Secrets are AES-GCM encrypted (app.core.secretbox), never plain.
    mfa_secret: Mapped[str | None] = mapped_column(Text, nullable=True)  # the confirmed one
    mfa_pending_secret: Mapped[str | None] = mapped_column(Text, nullable=True)  # during enrolment
    mfa_enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The last 30-second step a code was accepted for: a code works once only.
    mfa_last_step: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Seeded demo account: in demo mode it skips two-step enforcement (Phase 13).
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false", nullable=False)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Bumped on password change, deactivation and role change: every access token minted
    # before the bump stops working immediately.
    session_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)

    sites: Mapped[list[Site]] = relationship(
        secondary=user_site_assignments, lazy="selectin", order_by=Site.code
    )
    # Clients only (Phase 12): the projects they may see.
    client_projects: Mapped[list["Project"]] = relationship(
        secondary=project_clients, lazy="selectin", order_by="Project.code"
    )

    __table_args__ = (
        CheckConstraint("mfa_enabled = (mfa_secret IS NOT NULL)", name="mfa_secret_when_enabled"),
        CheckConstraint("mfa_enabled = (mfa_enabled_at IS NOT NULL)", name="mfa_enabled_dated"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        CheckConstraint("failed_login_count >= 0", name="failed_login_count_non_negative"),
    )


class RefreshToken(UUIDPrimaryKeyMixin, Base):
    """One row per issued refresh token. Rotation chains tokens of one sign-in into a family."""

    __tablename__ = "refresh_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    family_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    replaced_by_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(200), nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)


class MfaRecoveryCode(UUIDPrimaryKeyMixin, Base):
    """A one-use code for when the authenticator is lost (Phase 13). Stored keyed-hashed, never plain."""

    __tablename__ = "mfa_recovery_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (UniqueConstraint("user_id", "code_hash", name="uq_mfa_recovery_codes_user_code"),)
