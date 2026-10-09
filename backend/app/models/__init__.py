"""Import every model module here so Alembic autogenerate sees the full metadata."""

from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.user import RefreshToken, RoleRecord, Site, User, user_site_assignments

__all__ = ["AuditLog", "Base", "RefreshToken", "RoleRecord", "Site", "User", "user_site_assignments"]
