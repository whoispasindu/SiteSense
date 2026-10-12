"""The handover date the client sees (Phase 12): published by the project manager, with a reason.

The client sees one date. The PM chooses it, helped by the programme's forecast at current rates
(Phase 9) and the risk model's likely range (Phase 10), and writes a reason for the client. Until a
date is published the client sees the contract's planned end.

The PM's dashboard reminds them when a published date looks out of date:

- the programme forecast is more than 7 working days later than it; or
- nobody has reviewed it in 30 days.

The PM then republishes, or confirms it unchanged. Both are recorded (append-only) and audited, and
a new date is announced to the project's clients.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError
from app.core.logging import get_logger
from app.core.permissions import Permission, Role, has_permission
from app.core.scoping import scope_to_user_sites
from app.models import HandoverPublication, Project, ProjectStatus, RiskScore, User
from app.schemas.portal import (
    DateRange,
    HandoverEntryOut,
    HandoverIn,
    HandoverReminder,
    HandoverReminderItem,
    HandoverState,
    HandoverSuggestions,
)
from app.services import audit, calendar_service, client_access, network_service, notification_service
from app.services.audit import RequestMeta
from app.services.notification_service import NewNotification

log = get_logger(__name__)

STALE_WORKING_DAYS = 7
REVIEW_DAYS = 30
HISTORY_LIMIT = 50
MAX_YEARS_AHEAD = 15
OPEN_STATUSES = (ProjectStatus.PLANNING.value, ProjectStatus.ACTIVE.value, ProjectStatus.ON_HOLD.value)


def entries(db: Session, project_id: uuid.UUID, limit: int = HISTORY_LIMIT) -> list[HandoverPublication]:
    """Publications and reviews, newest first."""
    return list(
        db.scalars(
            select(HandoverPublication)
            .where(HandoverPublication.project_id == project_id)
            .order_by(HandoverPublication.published_at.desc(), HandoverPublication.id)
            .limit(limit)
        )
    )


def latest_published(db: Session, project_id: uuid.UUID) -> HandoverPublication | None:
    return db.scalar(
        select(HandoverPublication)
        .where(HandoverPublication.project_id == project_id, HandoverPublication.kind == "published")
        .order_by(HandoverPublication.published_at.desc())
        .limit(1)
    )


def programme_forecast(db: Session, project: Project) -> date | None:
    """The programme's forecast end at current rates, or None when it cannot be worked out."""
    try:
        return network_service.analyse(db, project).forecast_end
    except Exception:  # a programme the network cannot read must not hide the handover date
        log.exception("handover_forecast_failed", project=project.code)
        return None


def reminder(
    db: Session, project: Project, rows: list[HandoverPublication], forecast: date | None, now: datetime
) -> HandoverReminder | None:
    """Why the published date may be out of date, or None while it looks current (or is unpublished)."""
    published = latest_published(db, project.id)
    if published is None or not rows:
        return None
    reasons: list[str] = []
    gap: int | None = None
    if forecast is not None:
        gap = calendar_service.calendar_for(db, project).gap(published.handover_date, forecast)
        if gap > STALE_WORKING_DAYS:
            reasons.append(
                f"The programme now forecasts {forecast:%d %b %Y}, "
                f"{gap} working days after the published date."
            )
    days = (now - rows[0].published_at).days
    if days >= REVIEW_DAYS:
        reasons.append(f"Not reviewed for {days} days.")
    if not reasons:
        return None
    return HandoverReminder(reasons=reasons, forecast_gap_days=gap, days_since_review=days)


def _entry(row: HandoverPublication, names: dict[uuid.UUID, str]) -> HandoverEntryOut:
    return HandoverEntryOut(
        kind="published" if row.kind == "published" else "confirmed",
        handover_date=row.handover_date,
        reason=row.reason,
        programme_forecast=row.programme_forecast,
        published_by=names.get(row.published_by, "A former user"),
        published_at=row.published_at,
    )


def _risk_range(db: Session, project: Project) -> DateRange | None:
    row = db.scalar(
        select(RiskScore)
        .where(RiskScore.project_id == project.id)
        .order_by(RiskScore.score_date.desc())
        .limit(1)
    )
    if row is None or not row.ranges:
        return None
    delay = row.ranges.get("delay_days") or {}
    try:
        low, high = round(float(delay["low"])), round(float(delay["high"]))
    except (KeyError, TypeError, ValueError):
        return None
    return DateRange(
        start=project.planned_end + timedelta(days=low), end=project.planned_end + timedelta(days=high)
    )


def state(db: Session, user: User, project: Project) -> HandoverState:
    rows = entries(db, project.id)
    names = dict(
        db.execute(select(User.id, User.full_name).where(User.id.in_({r.published_by for r in rows}))).all()
    )
    forecast = programme_forecast(db, project)
    role = Role(user.role)
    published = next((r for r in rows if r.kind == "published"), None)
    return HandoverState(
        project_id=project.id,
        current=_entry(rows[0], names) if rows else None,
        published=_entry(published, names) if published else None,
        history=[_entry(r, names) for r in rows],
        suggestions=HandoverSuggestions(
            contract_end=project.planned_end,
            programme_forecast=forecast,
            risk_range=_risk_range(db, project) if has_permission(role, Permission.RISK_READ) else None,
        ),
        reminder=reminder(db, project, rows, forecast, clock.utcnow()),
        can_publish=has_permission(role, Permission.PROJECTS_MANAGE),
    )


def _check_date(project: Project, day: date) -> None:
    if day < project.start_date:
        raise BusinessRuleError("The handover date cannot be before the project starts.")
    if day > project.start_date.replace(year=project.start_date.year + MAX_YEARS_AHEAD):
        raise BusinessRuleError(f"The handover date must be within {MAX_YEARS_AHEAD} years of the start.")


def _lock(db: Session, project: Project) -> None:
    # One publication at a time per project, so two quick saves cannot interleave.
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update())


def publish(
    db: Session, user: User, project: Project, data: HandoverIn, *, meta: RequestMeta
) -> HandoverPublication:
    _check_date(project, data.handover_date)
    _lock(db, project)
    before = latest_published(db, project.id)
    row = HandoverPublication(
        project_id=project.id,
        kind="published",
        handover_date=data.handover_date,
        reason=data.reason,
        programme_forecast=programme_forecast(db, project),
        published_by=user.id,
        published_at=clock.utcnow(),
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        audit.AuditAction.HANDOVER_PUBLISHED,
        meta=meta,
        actor_id=user.id,
        target_type="project",
        target_id=project.id,
        details={
            "before": before.handover_date.isoformat() if before else None,
            "after": data.handover_date.isoformat(),
            "programme_forecast": row.programme_forecast.isoformat() if row.programme_forecast else None,
        },
    )
    if before is None or before.handover_date != data.handover_date:
        clients = client_access.clients_of(db, project.id)
        notification_service.send(
            db,
            [
                NewNotification(
                    user_id=client.id,
                    kind="handover_published",
                    title=f"New handover date for {project.name}"[:160],
                    body=f"{data.handover_date:%d %B %Y}. {data.reason}"[:500],
                    link=f"/client/projects/{project.id}",
                    project_id=project.id,
                    dedupe_key=f"handover:{row.id}",
                )
                for client in clients
            ],
        )
    db.commit()
    return row


def confirm(db: Session, user: User, project: Project, *, meta: RequestMeta) -> HandoverPublication:
    """The PM reviewed the published date and keeps it: resets the 30-day reminder. Not sent to clients."""
    _lock(db, project)
    published = latest_published(db, project.id)
    if published is None:
        raise ConflictError("Publish a handover date before confirming it.")
    row = HandoverPublication(
        project_id=project.id,
        kind="confirmed",
        handover_date=published.handover_date,
        reason=published.reason,
        programme_forecast=programme_forecast(db, project),
        published_by=user.id,
        published_at=clock.utcnow(),
    )
    db.add(row)
    db.flush()
    audit.record(
        db,
        audit.AuditAction.HANDOVER_CONFIRMED,
        meta=meta,
        actor_id=user.id,
        target_type="project",
        target_id=project.id,
        details={
            "date": published.handover_date.isoformat(),
            "programme_forecast": row.programme_forecast.isoformat() if row.programme_forecast else None,
        },
    )
    db.commit()
    return row


def reminders(db: Session, user: User) -> list[HandoverReminderItem]:
    """Published dates on the PM's open projects that look out of date (the dashboard)."""
    published_projects = select(HandoverPublication.project_id).distinct()
    projects = db.scalars(
        scope_to_user_sites(
            select(Project)
            .where(Project.status.in_(OPEN_STATUSES), Project.id.in_(published_projects))
            .order_by(Project.code),
            Project.site_id,
            user,
        )
    ).all()
    now = clock.utcnow()
    out: list[HandoverReminderItem] = []
    for project in projects:
        rows = entries(db, project.id, limit=HISTORY_LIMIT)
        found = reminder(db, project, rows, programme_forecast(db, project), now)
        published = next((r for r in rows if r.kind == "published"), None)
        if found is not None and published is not None:
            out.append(
                HandoverReminderItem(
                    project_id=project.id,
                    code=project.code,
                    name=project.name,
                    published_date=published.handover_date,
                    reminder=found,
                )
            )
    return out
