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
from app.ai.risk import scoring, whatif
from app.core import clock
from app.core.logging import get_logger
from app.core.permissions import Role
from app.models import BudgetLine, Project, ProjectStatus, RiskScore, User
from app.schemas.risk import (
    AdviceOut,
    DriverOut,
    EffectOut,
    ForecastOut,
    ProjectRisk,
    RangeOut,
    Ranges,
    RiskHistoryPoint,
    RiskOut,
    RiskRanking,
    ScoreRange,
    WhatIfActionIn,
    WhatIfActionOut,
    WhatIfIn,
    WhatIfOut,
)
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
    ranges = {
        "delay_days": {"low": round(delay.low, 1), "high": round(delay.high, 1)},
        "overrun_pct": {"low": round(overrun.low, 2), "high": round(overrun.high, 2)},
        "score": {
            "low": scoring.risk_score(delay.low, overrun.low, planned_days),
            "high": scoring.risk_score(delay.high, overrun.high, planned_days),
        },
    }
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
        "ranges": ranges,
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
        _alert(db, project, score, delay, overrun, drivers, on)
    db.commit()
    return Scored(project.id, score, level, alerted)


def forecast_text(delay: risk_model.Prediction, overrun: risk_model.Prediction) -> str:
    """The forecast in words, always with its likely range."""
    return (
        f"about {delay.value:.0f} days late (likely {delay.low:.0f} to {delay.high:.0f}) and "
        f"{overrun.value:.1f}% over budget (likely {overrun.low:.1f} to {overrun.high:.1f}%)"
    )


def _alert(
    db: Session,
    project: Project,
    score: int,
    delay: risk_model.Prediction,
    overrun: risk_model.Prediction,
    drivers: list[scoring.Driver],
    on: date,
) -> None:
    """BR-10: tell the site's project managers that the project has become high risk."""
    signals = [d.label.lower() for d in drivers if d.kind == "signal"][:2]
    reason = f" Main factors: {' and '.join(signals)}." if signals else ""
    reason = f" Forecast: {forecast_text(delay, overrun)}.{reason}"
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


def _ranges(row: RiskScore) -> Ranges | None:
    return Ranges.model_validate(row.ranges) if row.ranges else None


def _out(row: RiskScore) -> RiskOut:
    return RiskOut(
        score_date=row.score_date,
        score=row.score,
        level=row.level,
        delay_days=row.delay_days,
        overrun_pct=row.overrun_pct,
        ranges=_ranges(row),
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
        history=[
            RiskHistoryPoint(
                date=r.score_date,
                score=r.score,
                level=r.level,
                score_range=ScoreRange.model_validate(r.ranges["score"]) if r.ranges else None,
            )
            for r in rows
        ],
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
                ranges=_ranges(row) if row else None,
                top_driver=f"{top['label']}: {top['value']}" if top else None,
                score_date=row.score_date if row else None,
            )
        )
    return sorted(out, key=lambda r: (r.score is None, -(r.score or 0), r.code))


# --- What-if planner (Phase 10) ----------------------------------------------------------------------


def _forecast(
    model: risk_model.RiskModel, values: dict[str, float], planned_days: float, extra_cost_pct: float = 0.0
) -> ForecastOut:
    """The model's forecast for these inputs, with its likely range; ``extra_cost_pct`` adds entered costs."""
    delay, overrun = model.predict(tuple(values[name] for name in model.features))
    cost, cost_low, cost_high = (v + extra_cost_pct for v in (overrun.value, overrun.low, overrun.high))
    score = scoring.risk_score(delay.value, cost, planned_days)
    return ForecastOut(
        delay_days=round(delay.value, 1),
        delay_range=RangeOut(low=round(delay.low, 1), high=round(delay.high, 1)),
        overrun_pct=round(cost, 2),
        overrun_range=RangeOut(low=round(cost_low, 2), high=round(cost_high, 2)),
        score=score,
        score_range=ScoreRange(
            low=scoring.risk_score(delay.low, cost_low, planned_days),
            high=scoring.risk_score(delay.high, cost_high, planned_days),
        ),
        level=scoring.level(score),
    )


def _saved(
    model: risk_model.RiskModel, before: dict[str, float], ids: list[str]
) -> tuple[EffectOut, EffectOut]:
    """What the actions save, from half their planned change (low) to all of it (high)."""
    delay0, overrun0 = model.predict(tuple(before[n] for n in model.features))
    ends = []
    for strength in (whatif.HALF, whatif.FULL):
        after = whatif.applied(before, ids, strength)
        delay, overrun = model.predict(tuple(after[n] for n in model.features))
        ends.append((delay0.value - delay.value, overrun0.value - overrun.value))
    (d_low, o_low), (d_high, o_high) = ends
    return (
        EffectOut(low=round(min(d_low, d_high), 1), high=round(max(d_low, d_high), 1)),
        EffectOut(low=round(min(o_low, o_high), 2), high=round(max(o_low, o_high), 2)),
    )


def what_if(db: Session, user: User, project_id: uuid.UUID, data: WhatIfIn) -> WhatIfOut:
    """Test recovery actions on today's forecast. Nothing is stored and nothing in the project changes."""
    project = project_service.get_project(db, user, project_id)  # 404 outside the user's sites
    today = clock.site_today()
    model = risk_model.current()
    built = feature_builder.build(db, project, today)
    values = built.values
    planned_days = values["planned_duration_days"]
    budget = db.scalar(
        select(func.coalesce(func.sum(BudgetLine.budget_amount), 0)).where(
            BudgetLine.project_id == project.id
        )
    ) or Decimal(0)
    notes = list(built.notes)
    if budget <= 0:
        notes.append("No cost budget yet: entered action costs cannot be added to the cost forecast.")

    def pct(cost: Decimal | None) -> float | None:
        return float(cost / budget * 100) if cost is not None and budget > 0 else None

    chosen: dict[str, WhatIfActionIn] = {a.id: a for a in data.actions}
    actions = []
    for action in whatif.CATALOGUE:
        delay_saved, overrun_saved = _saved(model, values, [action.id])
        entered = chosen.get(action.id)
        actions.append(
            WhatIfActionOut(
                id=action.id,
                label=action.label,
                description=action.description,
                change=whatif.describe_change(
                    action, values, whatif.applied(values, [action.id], whatif.FULL)
                ),
                selected=entered is not None,
                delay_saved_days=delay_saved,
                overrun_saved_pct=overrun_saved,
                cost=entered.cost if entered else None,
                cost_pct=round(p, 3) if entered and (p := pct(entered.cost)) is not None else None,
            )
        )

    plan = plan_delay = plan_overrun = None
    if chosen:
        ids = [str(action_id) for action_id in chosen]
        added = sum(p for a in chosen.values() if (p := pct(a.cost)) is not None)
        plan = _forecast(model, whatif.applied(values, ids, whatif.FULL), planned_days, added)
        plan_delay, model_overrun = _saved(model, values, ids)
        plan_overrun = EffectOut(
            low=round(model_overrun.low - added, 2), high=round(model_overrun.high - added, 2)
        )
    return WhatIfOut(
        project_id=project.id,
        as_of=today,
        model_version=model.version,
        baseline=_forecast(model, values, planned_days),
        actions=actions,
        plan=plan,
        plan_delay_saved_days=plan_delay,
        plan_overrun_saved_pct=plan_overrun,
        costs_not_entered=[whatif.BY_ID[a.id].label for a in data.actions if a.cost is None],
        advice=[AdviceOut(id=a.id, label=a.label, text=a.text) for a in whatif.advice(values)],
        notes=notes,
    )
