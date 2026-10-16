"""Issues in daily reports and their follow-up actions (Phase 7).

Reading needs ``reports:read`` (PM, QS, site engineers) on the report's site. Analysing and confirming
are for the report's author on the day it was filed; closing a stop-work flag is for the project
manager (BR-11). Those finer checks are in ``issue_service``.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, Meta, rate_limit, require_permission
from app.core.permissions import Permission
from app.models import User
from app.schemas.issues import ActionOut, CloseActionIn, ConfirmIn, ReportIssues, StopScopeIn
from app.services import issue_service

router = APIRouter(tags=["issues"])

Reader = Annotated[User, Depends(require_permission(Permission.REPORTS_READ))]


@router.get("/reports/{report_id}/issues", response_model=ReportIssues)
def report_issues(report_id: uuid.UUID, user: Reader, db: DbSession) -> ReportIssues:
    return issue_service.get_issues(db, user, report_id)


@router.post(
    "/reports/{report_id}/analyze",
    response_model=ReportIssues,
    dependencies=[Depends(rate_limit("analyze", "analyze_rate_per_minute", per_user=True))],
)
def analyze_report(report_id: uuid.UUID, user: Reader, db: DbSession) -> ReportIssues:
    """Tag the report's problems. Suggestions only: nothing changes until the author confirms."""
    return issue_service.analyze(db, user, report_id)


@router.post("/reports/{report_id}/issues/confirm", response_model=ReportIssues)
def confirm_issues(
    report_id: uuid.UUID, body: ConfirmIn, user: Reader, db: DbSession, meta: Meta
) -> ReportIssues:
    return issue_service.confirm(db, user, report_id, body, meta=meta)


@router.post("/report-actions/{action_id}/close", response_model=ActionOut)
def close_action(
    action_id: uuid.UUID, body: CloseActionIn, user: Reader, db: DbSession, meta: Meta
) -> ActionOut:
    return issue_service.close_action(db, user, action_id, body.resolution, meta=meta)


@router.put("/report-actions/{action_id}/stop-scope", response_model=ActionOut)
def set_stop_scope(
    action_id: uuid.UUID, body: StopScopeIn, user: Reader, db: DbSession, meta: Meta
) -> ActionOut:
    """BR-11: the PM changes what an open stop-work flag stops (chosen tasks or the whole project)."""
    return issue_service.set_stop_scope(db, user, action_id, body, meta=meta)


@router.get("/projects/{project_id}/report-actions", response_model=list[ActionOut])
def open_actions(project_id: uuid.UUID, user: Reader, db: DbSession) -> list[ActionOut]:
    """Open follow-ups on the project, stop-work flags first."""
    return issue_service.open_actions(db, user, project_id)
