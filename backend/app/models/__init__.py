"""Import every model module here so Alembic autogenerate sees the full metadata."""

from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.materials import (
    Approval,
    Delivery,
    DocumentCounter,
    MaterialRequest,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    RequestStatus,
    Supplier,
)
from app.models.project import BoqItem, BoqSection, BudgetLine, Project, ProjectStatus, ProjectType
from app.models.report import DailyReport, Notification, ReportPhoto, ReportProgress, WeatherForecast
from app.models.schedule import ProgressSnapshot, Task
from app.models.user import RefreshToken, RoleRecord, Site, User, user_site_assignments

__all__ = [
    "Approval",
    "AuditLog",
    "Base",
    "BoqItem",
    "BoqSection",
    "BudgetLine",
    "DailyReport",
    "Delivery",
    "DocumentCounter",
    "MaterialRequest",
    "Notification",
    "ProgressSnapshot",
    "Project",
    "ProjectStatus",
    "ProjectType",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "PurchaseOrderStatus",
    "RefreshToken",
    "ReportPhoto",
    "ReportProgress",
    "RequestStatus",
    "RoleRecord",
    "Site",
    "Supplier",
    "Task",
    "User",
    "WeatherForecast",
    "user_site_assignments",
]
