"""Audit trail: every login, logout and administrative change is recorded here."""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core import clock
from app.models import AuditLog


@dataclass(frozen=True, slots=True)
class RequestMeta:
    """Who is calling from where; captured once per request and passed to services."""

    ip_address: str | None
    user_agent: str | None

    @classmethod
    def build(cls, ip_address: str | None, user_agent: str | None) -> "RequestMeta":
        return cls(ip_address=(ip_address or None), user_agent=(user_agent or "")[:200] or None)


class AuditAction:
    LOGIN_SUCCEEDED = "auth.login_succeeded"
    LOGIN_FAILED = "auth.login_failed"
    ACCOUNT_LOCKED = "auth.account_locked"
    LOGOUT = "auth.logout"
    REFRESH_REUSE_DETECTED = "auth.refresh_reuse_detected"
    PASSWORD_CHANGED = "auth.password_changed"  # noqa: S105 - event name
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_REACTIVATED = "user.reactivated"
    USER_PASSWORD_RESET = "user.password_reset"  # noqa: S105 - event name
    USER_SITES_ASSIGNED = "user.sites_assigned"
    USER_PROJECTS_ASSIGNED = "user.projects_assigned"  # Phase 12: a client's projects
    SITE_CREATED = "site.created"
    SITE_UPDATED = "site.updated"
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    BOQ_IMPORTED = "boq.imported"
    BUDGET_LINE_UPDATED = "budget_line.updated"
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_PROGRESS_UPDATED = "task.progress_updated"
    TASK_DELETED = "task.deleted"
    REPORT_CREATED = "report.created"
    REPORT_UPDATED = "report.updated"
    REPORT_PHOTO_ADDED = "report.photo_added"
    REPORT_PHOTO_DELETED = "report.photo_deleted"
    REQUEST_CREATED = "material_request.created"
    REQUEST_UPDATED = "material_request.updated"
    REQUEST_DECIDED = "material_request.decided"
    REQUEST_RETURNED = "material_request.returned_for_approval"
    SUPPLIER_CREATED = "supplier.created"
    SUPPLIER_UPDATED = "supplier.updated"
    PURCHASE_ORDER_ISSUED = "purchase_order.issued"
    DELIVERY_RECORDED = "delivery.recorded"
    REPORT_ISSUES_CONFIRMED = "report.issues_confirmed"
    REPORT_ACTION_CLOSED = "report_action.closed"
    # Phase 8: claims, variations and the BR-09 limit
    CLAIM_SUBMITTED = "claim.submitted"
    CLAIM_DECIDED = "claim.decided"
    CLAIM_PAID = "claim.paid"
    VARIATION_RAISED = "variation.raised"
    VARIATION_PRICED = "variation.priced"
    VARIATION_REVISED = "variation.revised"
    VARIATION_DECIDED = "variation.decided"
    VARIATION_CLIENT_DECIDED = "variation.client_decided"
    VARIATION_APPLIED = "variation.applied"
    VARIATION_WITHDRAWN = "variation.withdrawn"
    VARIATION_LIMIT_CHANGED = "project.variation_limit_changed"
    # Phase 9: the programme network, holidays and stop-work scope
    DEPENDENCY_ADDED = "task.dependency_added"
    DEPENDENCY_REMOVED = "task.dependency_removed"
    HOLIDAY_ADDED = "holiday.added"
    HOLIDAY_REMOVED = "holiday.removed"
    STOP_WORK_SCOPE_CHANGED = "report_action.stop_scope_changed"
    CRITICAL_PATH_OVERRIDE = "material_request.critical_path_set"
    # Phase 11: email choices and the weekly PDF (a cost export)
    NOTIFICATION_PREFERENCES_CHANGED = "user.notification_preferences_changed"
    WEEKLY_REPORT_DOWNLOADED = "report.weekly_downloaded"
    # Phase 12: the client portal
    HANDOVER_PUBLISHED = "project.handover_published"
    HANDOVER_CONFIRMED = "project.handover_confirmed"
    PHOTOS_CLIENT_SHARE_CHANGED = "photo.client_share_changed"


def record(
    db: Session,
    action: str,
    *,
    meta: RequestMeta | None = None,
    actor_id: uuid.UUID | None = None,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    details: dict[str, Any] | None = None,
) -> AuditLog:
    """Add an audit entry to the current transaction. The caller commits."""
    entry = AuditLog(
        # App clock (not the database's transaction time) so events in one transaction keep order.
        occurred_at=clock.utcnow(),
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        ip_address=meta.ip_address if meta else None,
        user_agent=meta.user_agent if meta else None,
        details=details or {},
    )
    db.add(entry)
    return entry
