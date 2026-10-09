"""Import every model module here so Alembic autogenerate sees the full metadata."""

from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.project import BoqItem, BoqSection, BudgetLine, Project, ProjectStatus, ProjectType
from app.models.schedule import ProgressSnapshot, Task
from app.models.user import RefreshToken, RoleRecord, Site, User, user_site_assignments

__all__ = [
    "AuditLog",
    "Base",
    "BoqItem",
    "BoqSection",
    "BudgetLine",
    "ProgressSnapshot",
    "Project",
    "ProjectStatus",
    "ProjectType",
    "RefreshToken",
    "RoleRecord",
    "Site",
    "Task",
    "User",
    "user_site_assignments",
]
