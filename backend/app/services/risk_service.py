"""Daily risk scoring (Phase 6): build features from live data, run the model, store, alert (BR-10).

Every open project (planning, active, on hold) is scored once a day by the scheduler, again after a
daily report is filed, and on demand from the CLI. Re-scoring on the same day replaces that day's
row, so the history keeps one score per project per day.

The model only suggests: a score never changes anything in the project by itself. A High score
alerts the site's project managers (BR-10) when a project *enters* High, not every day it stays
there.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ai.risk import features as feature_builder
from app.ai.risk import model as risk_model
from app.ai.risk import scoring
from app.core import clock
from app.core.logging import get_logger
from app.core.permissions import Role
from app.models import Project, ProjectStatus, RiskScore, User
from app.schemas.risk import DriverOut, ProjectRisk, RiskHistoryPoint, RiskOut, RiskRanking
from app.services import notification_service, project_service
from app.services.notification_service import NewNotification

log = get_logger(__name__)

SCORED_STATUSES = (ProjectStatus.PLANNING.value, ProjectStatus.ACTIVE.value, ProjectStatus.ON_HOLD.value)
HISTORY_DAYS = 14


@dataclass(frozen=True, slots=True)
class Scored:
    project_id: uuid.UUID
    score: int
    level: str
    alerted: bool


def score_project(
    db: Session, project: Project, on: date, model: risk_model.RiskModel | None = None
) -> Scored:
    """Score one project for ``on`` and store it (replacing that day's score). Commits."""
    model = model or risk_model.current()
    built = feature_builder.build(db, project, on)
    delay, overrun = model.predict(built.vector())
    planned_days = built.values["planned_duration_days"]
    score = scoring.risk_score(delay.value, overrun.value, planned_days)
    level = scoring.level(score)
    drivers = scoring.drivers(
        model.features,
        built.values,
        delay.contributions,
        overrun.contributions,
        planned_duration_days=planned_days,
    )
    # The state before this scoring: the latest score up to and including today (a same-day re-score
    # compares with this morning's score, so a project that was already High does not alert again).
    previous = db.scalar(
        select(RiskScore)
        .where(RiskScore.project_id == project.id, RiskScore.score_date <= on)
        .order_by(RiskScore.score_date.desc())
        .limit(1)
    )
    row = {
        "id": uuid.uuid4(),
        "project_id": project.id,
        "score_date": on,
        "score": score,
        "level": level,
        "delay_days": Decimal(str(round(delay.value, 1))),
        "overrun_pct": Decimal(str(round(overrun.value, 2))),
        "ranges": None,
        "drivers": [d.as_dict() for d in drivers],
        "features": {"values": built.values, "notes": built.notes},
        "model_version": model.version,
        "created_at": clock.utcnow(),
    }
    stmt = insert(RiskScore).values(**row)
    db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_risk_scores_project_date",
            set_={k: stmt.excluded[k] for k in row if k not in ("id", "project_id", "score_date")},
        )
    )
    alerted = level == "high" and (previous is None or previous.level != "high")
    if alerted:
        _alert(db, project, score, drivers, on)
    db.commit()
    return Scored(project.id, score, level, alerted)


def _alert(db: Session, project: Project, score: int, drivers: list[scoring.Driver], on: date) -> None:
    """BR-10: tell the site's project managers that the project has become high risk."""
    signals = [d.label.lower() for d in drivers if d.kind == "signal"][:2]
    reason = f" Main factors: {' and '.join(signals)}." if signals else ""
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=pm.id,
                kind="risk_high",
                title=f"{project.code} is now high risk ({score})",
                body=f"The risk forecast for {project.name} has reached High.{reason}",
                link=f"/projects/{project.id}",
                project_id=project.id,
                dedupe_key=f"risk-high:{project.id}:{on.isoformat()}",
            )
            for pm in notification_service.site_people(db, project.site_id, {Role.PROJECT_MANAGER})
        ],
    )


def score_all(db: Session, on: date | None = None) -> list[Scored]:
    """Score every open project. One failing project is logged and skipped, never stops the rest."""
    on = on or clock.site_today()
    model = risk_model.current()
    results = []
    projects = db.scalars(
        select(Project).where(Project.status.in_(SCORED_STATUSES)).order_by(Project.code)
    ).all()
    for project in projects:
        try:
            results.append(score_project(db, project, on, model))
        except Exception:
            db.rollback()
            log.exception("risk_scoring_failed", project=project.code)
    log.info("risk_scored", projects=len(results), high=sum(1 for r in results if r.level == "high"))
    return results


def rescore_after_report(db: Session, project: Project) -> None:
    """Best effort after a daily report: the report is saved even if scoring fails."""
    if project.status not in SCORED_STATUSES:
        return
    try:
        score_project(db, project, clock.site_today())
    except Exception:
        db.rollback()
        log.exception("risk_rescore_failed", project=project.code)


# --- Reading --------------------------------------------------------------------------------------


def _out(row: RiskScore) -> RiskOut:
    return RiskOut(
        score_date=row.score_date,
        score=row.score,
        level=row.level,
        delay_days=row.delay_days,
        overrun_pct=row.overrun_pct,
        drivers=[DriverOut.model_validate(d) for d in row.drivers],
        notes=list(row.features.get("notes", [])),
        model_version=row.model_version,
        scored_at=row.created_at,
    )


def project_risk(db: Session, user: User, project_id: uuid.UUID) -> ProjectRisk:
    project = project_service.get_project(db, user, project_id)  # 404 outside the user's sites
    since = clock.site_today() - timedelta(days=HISTORY_DAYS - 1)
    rows = db.scalars(
        select(RiskScore)
        .where(RiskScore.project_id == project.id, RiskScore.score_date >= since)
        .order_by(RiskScore.score_date)
    ).all()
    latest = db.scalar(
        select(RiskScore)
        .where(RiskScore.project_id == project.id)
        .order_by(RiskScore.score_date.desc())
        .limit(1)
    )
    return ProjectRisk(
        project_id=project.id,
        latest=_out(latest) if latest else None,
        history=[RiskHistoryPoint(date=r.score_date, score=r.score, level=r.level) for r in rows],
    )


def _raises(driver: dict[str, Any]) -> bool:
    """A signal (something the site can act on) that pushes the forecast up: the reason worth naming."""
    return driver.get("kind") == "signal" and (
        driver.get("delay_days", 0) > 0 or driver.get("overrun_pct", 0) > 0
    )


def ranking(db: Session, user: User) -> list[RiskRanking]:
    """Every project the user can see with its latest score, highest risk first (the dashboard)."""
    projects = project_service.list_projects(db, user)
    if not projects:
        return []
    ids = [p.id for p in projects]
    latest_dates = (
        select(RiskScore.project_id, func.max(RiskScore.score_date).label("score_date"))
        .where(RiskScore.project_id.in_(ids))
        .group_by(RiskScore.project_id)
        .subquery()
    )
    rows = db.scalars(
        select(RiskScore).join(
            latest_dates,
            (latest_dates.c.project_id == RiskScore.project_id)
            & (latest_dates.c.score_date == RiskScore.score_date),
        )
    ).all()
    by_project = {r.project_id: r for r in rows}
    out = []
    for p in projects:
        if p.status not in SCORED_STATUSES:
            continue
        row = by_project.get(p.id)
        top = next((d for d in (row.drivers if row else []) if _raises(d)), None)
        out.append(
            RiskRanking(
                project_id=p.id,
                code=p.code,
                name=p.name,
                site_code=p.site.code,
                status=p.status,
                score=row.score if row else None,
                level=row.level if row else None,
                delay_days=row.delay_days if row else None,
                overrun_pct=row.overrun_pct if row else None,
                top_driver=f"{top['label']}: {top['value']}" if top else None,
                score_date=row.score_date if row else None,
            )
        )
    return sorted(out, key=lambda r: (r.score is None, -(r.score or 0), r.code))
