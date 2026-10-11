"""Issues in daily reports (Phase 7): AI suggestions, the author's confirmation, and follow-ups.

Flow
    1. After filing a report, its author asks for an analysis: each sentence of the problems text is
       tagged (category, severity, confidence) and stored as a suggestion. Asking again replaces the
       suggestions, until the tags are confirmed.
    2. The author confirms: keeps, edits or removes each suggestion, may add tags by hand, and ticks
       follow-ups. Nothing changes until this step; the AI only suggests.
    3. Confirmed follow-ups: a material request to raise (material delay), an alert to the site's
       project managers (high severity), a stop-work flag the project manager must clear (safety,
       BR-11). The project's risk is then re-scored, because confirmed issues are risk model inputs.

Only the report's author can analyse and confirm, on the day it was filed (the same window in which
the report itself can be corrected). Everyone who can read the report can read its issues.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.ai.nlp import model as text_model
from app.ai.nlp.tagger import LOW_CONFIDENCE, tag_problems
from app.ai.nlp.text import redact
from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import Role
from app.models import (
    ActionKind,
    ActionStatus,
    DailyReport,
    IssueStatus,
    Project,
    ReportAction,
    ReportActionTask,
    ReportIssue,
    Task,
    User,
)
from app.schemas.issues import ActionOut, ConfirmIn, IssueOut, ReportIssues, StopScopeIn
from app.services import audit, notification_service, project_service, report_service, risk_service
from app.services.audit import AuditAction, RequestMeta
from app.services.notification_service import NewNotification

MAX_SUMMARY = 500


def _people(db: Session, project: Project, report: DailyReport) -> list[str]:
    """Names to redact: everyone on the project's site, and the author."""
    roles = set(Role)
    names = [u.full_name for u in notification_service.site_people(db, project.site_id, roles)]
    return [*names, report.author.full_name]


def _issues(db: Session, report: DailyReport) -> list[ReportIssue]:
    return list(
        db.scalars(
            select(ReportIssue).where(ReportIssue.report_id == report.id).order_by(ReportIssue.position)
        )
    )


def _actions(db: Session, report: DailyReport) -> list[ReportAction]:
    return list(
        db.scalars(
            select(ReportAction).where(ReportAction.report_id == report.id).order_by(ReportAction.created_at)
        )
    )


def _confirmed(issues: list[ReportIssue], actions: list[ReportAction]) -> bool:
    return bool(actions) or any(i.status != IssueStatus.SUGGESTED.value for i in issues)


def _can_close(action: ReportAction, user: User, project: Project, author_id: uuid.UUID) -> bool:
    if action.status != ActionStatus.OPEN.value:
        return False
    if action.kind == ActionKind.STOP_WORK.value:  # BR-11: only the project manager clears stop-work
        return user.role == Role.PROJECT_MANAGER.value
    return user.id == author_id or user.role == Role.PROJECT_MANAGER.value


def _issue_out(issue: ReportIssue) -> IssueOut:
    return IssueOut(
        id=issue.id,
        snippet=issue.snippet,
        category=issue.category,
        severity=issue.severity,
        status=issue.status,
        source=issue.source,
        confidence=float(issue.confidence) if issue.confidence is not None else None,
        low_confidence=issue.low_confidence,
        ai_category=issue.ai_category,
        ai_severity=issue.ai_severity,
        edited=issue.source == "ai"
        and (issue.category != issue.ai_category or issue.severity != issue.ai_severity),
        confirmed_at=issue.confirmed_at,
    )


def action_out(action: ReportAction, user: User, project: Project, author_id: uuid.UUID) -> ActionOut:
    return ActionOut(
        id=action.id,
        report_id=action.report_id,
        kind=action.kind,
        status=action.status,
        summary=action.summary,
        created_at=action.created_at,
        closed_at=action.closed_at,
        request_id=action.request_id,
        can_close=_can_close(action, user, project, author_id),
        stop_scope=action.stop_scope,
        stop_task_ids=sorted(t.task_id for t in action.stop_tasks),
        can_edit_scope=action.kind == ActionKind.STOP_WORK.value
        and action.status == ActionStatus.OPEN.value
        and user.role == Role.PROJECT_MANAGER.value,
    )


def report_issues(db: Session, report: DailyReport, project: Project, user: User) -> ReportIssues:
    issues, actions = _issues(db, report), _actions(db, report)
    confirmed = _confirmed(issues, actions)
    versions = {i.model_version for i in issues if i.model_version}
    return ReportIssues(
        report_id=report.id,
        confirmed=confirmed,
        can_confirm=not confirmed and report_service.is_editable(report, user),
        model_version=max(versions) if versions else None,
        low_confidence_below=LOW_CONFIDENCE,
        issues=[_issue_out(i) for i in issues],
        actions=[action_out(a, user, project, report.author_id) for a in actions],
    )


def _editable(db: Session, user: User, report_id: uuid.UUID) -> tuple[DailyReport, Project]:
    report, project = report_service.get_report(db, user, report_id)  # 404 outside the user's sites
    if not report_service.is_editable(report, user):
        raise ForbiddenError("Only the report's author can check its issues, on the day it was filed.")
    # Lock the report so two analyses or confirmations (two tabs, a double submit) run one after the
    # other: the second then sees the first's result and gets 409 instead of duplicating follow-ups.
    db.execute(select(DailyReport.id).where(DailyReport.id == report.id).with_for_update())
    if _confirmed(_issues(db, report), _actions(db, report)):
        raise ConflictError("The issues in this report have already been confirmed.")
    return report, project


def analyze(
    db: Session, user: User, report_id: uuid.UUID, model: text_model.TextModel | None = None
) -> ReportIssues:
    """Tag the report's problems and store them as suggestions (replacing earlier suggestions)."""
    report, project = _editable(db, user, report_id)
    model = model or text_model.current()
    tags = tag_problems(report.problems, _people(db, project, report), model)
    db.execute(delete(ReportIssue).where(ReportIssue.report_id == report.id))
    now = clock.utcnow()
    for position, tag in enumerate(tags):
        db.add(
            ReportIssue(
                report_id=report.id,
                project_id=project.id,
                snippet=tag.snippet,
                category=tag.category,
                severity=tag.severity,
                status=IssueStatus.SUGGESTED.value,
                source="ai",
                ai_category=tag.category,
                ai_severity=tag.severity,
                confidence=Decimal(str(tag.confidence)),
                low_confidence=tag.low_confidence,
                model_version=tag.model_version,
                position=position,
                created_at=now,
            )
        )
    db.commit()
    return report_issues(db, report, project, user)


def _summary(issues: list[ReportIssue], category: str | None = None, severity: str | None = None) -> str:
    chosen = [
        i.snippet
        for i in issues
        if (category is None or i.category == category) and (severity is None or i.severity == severity)
    ]
    return "; ".join(chosen)[:MAX_SUMMARY]


def confirm(
    db: Session, user: User, report_id: uuid.UUID, data: ConfirmIn, *, meta: RequestMeta
) -> ReportIssues:
    report, project = _editable(db, user, report_id)
    suggestions = {i.id: i for i in _issues(db, report)}
    chosen_ids = [item.suggestion_id for item in data.issues if item.suggestion_id is not None]
    if len(chosen_ids) != len(set(chosen_ids)):
        raise BusinessRuleError("Each suggestion can be confirmed once.")
    unknown = set(chosen_ids) - set(suggestions)
    if unknown:
        raise BusinessRuleError("One of the suggestions does not belong to this report.")

    now = clock.utcnow()
    people = _people(db, project, report)
    confirmed: list[ReportIssue] = []
    position = len(suggestions)
    for item in data.issues:
        if item.suggestion_id is not None:
            issue = suggestions[item.suggestion_id]
            issue.category, issue.severity = item.category.value, item.severity.value
        else:
            assert item.snippet is not None  # checked by the schema
            issue = ReportIssue(
                report_id=report.id,
                project_id=project.id,
                snippet=redact(item.snippet, people),
                category=item.category.value,
                severity=item.severity.value,
                source="manual",
                low_confidence=False,
                position=position,
                created_at=now,
            )
            position += 1
            db.add(issue)
        issue.status = IssueStatus.CONFIRMED.value
        issue.confirmed_by, issue.confirmed_at = user.id, now
        confirmed.append(issue)
    for issue in suggestions.values():
        if issue.id not in set(chosen_ids):
            issue.status = IssueStatus.REMOVED.value
            issue.confirmed_by, issue.confirmed_at = user.id, now

    actions = _create_actions(db, user, report, project, confirmed, data, now)
    db.flush()
    audit.record(
        db,
        AuditAction.REPORT_ISSUES_CONFIRMED,
        meta=meta,
        actor_id=user.id,
        target_type="daily_report",
        target_id=report.id,
        details={
            "confirmed": len(confirmed),
            "removed": len(suggestions) - len(chosen_ids),
            "added": sum(1 for i in confirmed if i.source == "manual"),
            "edited": sum(
                1
                for i in confirmed
                if i.source == "ai" and (i.category, i.severity) != (i.ai_category, i.ai_severity)
            ),
            "actions": [a.kind for a in actions],
        },
    )
    db.commit()
    risk_service.rescore_after_report(db, project)  # confirmed issues are risk inputs
    return report_issues(db, report, project, user)


def _create_actions(
    db: Session,
    user: User,
    report: DailyReport,
    project: Project,
    confirmed: list[ReportIssue],
    data: ConfirmIn,
    now: datetime,
) -> list[ReportAction]:
    wanted = data.actions
    categories = {i.category for i in confirmed}
    created: list[ReportAction] = []

    def add(kind: ActionKind, summary: str, *, open_: bool, stop_scope: str | None = None) -> ReportAction:
        action = ReportAction(
            stop_scope=stop_scope,
            report_id=report.id,
            project_id=project.id,
            kind=kind.value,
            status=ActionStatus.OPEN.value if open_ else ActionStatus.DONE.value,
            summary=summary or "(no text)",
            created_by=user.id,
            created_at=now,
            closed_by=None if open_ else user.id,
            closed_at=None if open_ else now,
        )
        db.add(action)
        created.append(action)
        return action

    if wanted.material_request:
        if "material_delay" not in categories:
            raise BusinessRuleError("A material request follows from a confirmed material delay.")
        add(ActionKind.MATERIAL_REQUEST, _summary(confirmed, category="material_delay"), open_=True)
    if wanted.pm_alert:
        if not any(i.severity == "high" for i in confirmed):
            raise BusinessRuleError("An alert to the project manager follows from a high-severity issue.")
        add(ActionKind.PM_ALERT, _summary(confirmed, severity="high"), open_=False)
        _notify_pms(
            db,
            project,
            report,
            "issue_high",
            f"High-severity issue on {project.code}",
            _summary(confirmed, severity="high"),
        )
    if wanted.stop_work:
        if "safety" not in categories:
            raise BusinessRuleError("Stop-work follows from a confirmed safety issue.")
        ids = _validated_scope(db, project, wanted.stop_work_scope, wanted.stop_work_task_ids)
        flag = add(
            ActionKind.STOP_WORK,
            _summary(confirmed, category="safety"),
            open_=True,
            stop_scope=wanted.stop_work_scope,
        )
        flag.stop_tasks = [ReportActionTask(task_id=i) for i in sorted(ids)]
        _notify_pms(
            db,
            project,
            report,
            "stop_work",
            f"Stop-work flagged on {project.code}",
            _summary(confirmed, category="safety"),
        )
    return created


def _validated_scope(db: Session, project: Project, scope: str, task_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """BR-11: what a stop-work flag stops. "tasks" needs at least one task of this project.

    Validated before the flag is added, so no half-made flag is flushed by the query.
    """
    if scope != "tasks":
        return set()
    ids = set(task_ids)
    if not ids:
        raise BusinessRuleError("Choose the tasks the stop-work stops, or stop the whole project.")
    found = set(db.scalars(select(Task.id).where(Task.id.in_(ids), Task.project_id == project.id)).all())
    if found != ids:
        raise BusinessRuleError("Every stopped task must be in this project's programme.")
    return ids


def set_stop_scope(
    db: Session, user: User, action_id: uuid.UUID, data: StopScopeIn, *, meta: RequestMeta
) -> ActionOut:
    """The PM changes what an open stop-work flag stops (BR-11). Re-scores the project's risk."""
    action = db.scalars(
        select(ReportAction).where(ReportAction.id == action_id).with_for_update(of=ReportAction)
    ).first()
    if action is None:
        raise NotFoundError("Action not found.")
    report, project = report_service.get_report(db, user, action.report_id)  # 404 outside the user's sites
    if action.kind != ActionKind.STOP_WORK.value:
        raise BusinessRuleError("Only a stop-work flag stops tasks.")
    if action.status != ActionStatus.OPEN.value:
        raise ConflictError("This stop-work flag has been cleared.")
    if user.role != Role.PROJECT_MANAGER.value:
        raise ForbiddenError("Only the project manager changes what a stop-work flag stops.")
    before = {"scope": action.stop_scope, "tasks": sorted(str(t.task_id) for t in action.stop_tasks)}
    ids = _validated_scope(db, project, data.scope, data.task_ids)
    action.stop_scope = data.scope
    action.stop_tasks = [ReportActionTask(task_id=i) for i in sorted(ids)]
    audit.record(
        db,
        AuditAction.STOP_WORK_SCOPE_CHANGED,
        meta=meta,
        actor_id=user.id,
        target_type="report_action",
        target_id=action.id,
        details={
            "before": before,
            "after": {"scope": data.scope, "tasks": sorted(str(i) for i in ids)},
        },
    )
    db.commit()
    risk_service.rescore_after_report(db, project)  # stopped work changes the forecast
    db.refresh(action)
    return action_out(action, user, project, report.author_id)


def _notify_pms(db: Session, project: Project, report: DailyReport, kind: str, title: str, body: str) -> None:
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=pm.id,
                kind=kind,
                title=title,
                body=body[:300],
                link=f"/reports/{report.id}",
                project_id=project.id,
                dedupe_key=f"{kind}:{report.id}",
            )
            for pm in notification_service.site_people(db, project.site_id, {Role.PROJECT_MANAGER})
        ],
    )


def get_issues(db: Session, user: User, report_id: uuid.UUID) -> ReportIssues:
    report, project = report_service.get_report(db, user, report_id)
    return report_issues(db, report, project, user)


def close_action(
    db: Session, user: User, action_id: uuid.UUID, resolution: str, *, meta: RequestMeta
) -> ActionOut:
    action = db.get(ReportAction, action_id)
    if action is None:
        raise NotFoundError("Action not found.")
    report, project = report_service.get_report(db, user, action.report_id)  # 404 outside the user's sites
    if action.status != ActionStatus.OPEN.value:
        raise ConflictError("This action is already closed.")
    if not _can_close(action, user, project, report.author_id):
        if action.kind == ActionKind.STOP_WORK.value:
            raise ForbiddenError("Only the project manager can clear a stop-work flag.")
        raise ForbiddenError("Only the report's author or the project manager can close this.")
    action.status = resolution
    action.closed_by, action.closed_at = user.id, clock.utcnow()
    audit.record(
        db,
        AuditAction.REPORT_ACTION_CLOSED,
        meta=meta,
        actor_id=user.id,
        target_type="report_action",
        target_id=action.id,
        details={"kind": action.kind, "resolution": resolution, "report_id": str(report.id)},
    )
    db.commit()
    if action.kind == ActionKind.STOP_WORK.value:
        risk_service.rescore_after_report(db, project)  # BR-11: the stopped tasks can move again
    return action_out(action, user, project, report.author_id)


def open_actions(db: Session, user: User, project_id: uuid.UUID) -> list[ActionOut]:
    """Open follow-ups for a project (stop-work flags first), for the project page."""
    project = project_service.get_project(db, user, project_id)
    rows = db.execute(
        select(ReportAction, DailyReport.author_id)
        .join(DailyReport, DailyReport.id == ReportAction.report_id)
        .where(ReportAction.project_id == project.id, ReportAction.status == ActionStatus.OPEN.value)
        .order_by(ReportAction.kind != ActionKind.STOP_WORK.value, ReportAction.created_at.desc())
    ).all()
    return [action_out(action, user, project, author_id) for action, author_id in rows]
