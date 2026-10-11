"""Import every model module here so Alembic autogenerate sees the full metadata."""

from app.models.audit_log import AuditLog
from app.models.base import Base
from app.models.contract import (
    ClaimStatus,
    ProgressClaim,
    ProgressClaimLine,
    VariationEvent,
    VariationOrder,
)
from app.models.issues import (
    ActionKind,
    ActionStatus,
    IssueCategory,
    IssueSeverity,
    IssueStatus,
    ReportAction,
    ReportActionTask,
    ReportIssue,
)
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
from app.models.risk import RiskScore
from app.models.schedule import Holiday, ProgressSnapshot, Task, TaskDependency
from app.models.user import RefreshToken, RoleRecord, Site, User, user_site_assignments

__all__ = [
    "ActionKind",
    "ActionStatus",
    "Approval",
    "AuditLog",
    "Base",
    "BoqItem",
    "BoqSection",
    "BudgetLine",
    "ClaimStatus",
    "DailyReport",
    "Delivery",
    "DocumentCounter",
    "Holiday",
    "IssueCategory",
    "IssueSeverity",
    "IssueStatus",
    "MaterialRequest",
    "Notification",
    "ProgressClaim",
    "ProgressClaimLine",
    "ProgressSnapshot",
    "Project",
    "ProjectStatus",
    "ProjectType",
    "PurchaseOrder",
    "PurchaseOrderLine",
    "PurchaseOrderStatus",
    "RefreshToken",
    "ReportAction",
    "ReportActionTask",
    "ReportIssue",
    "ReportPhoto",
    "ReportProgress",
    "RequestStatus",
    "RiskScore",
    "RoleRecord",
    "Site",
    "Supplier",
    "Task",
    "TaskDependency",
    "User",
    "VariationEvent",
    "VariationOrder",
    "WeatherForecast",
    "user_site_assignments",
]
