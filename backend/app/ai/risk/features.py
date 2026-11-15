"""Build the risk model's features from live app data.

Each feature has exactly the meaning it has in the simulator the model was trained on
(``ml/data_generator/simulate.py``); a backend test checks that the names and order match the
model file. Where the app has no data yet (no programme, no reports, no forecast), the feature
takes its neutral value and a note says so, so the score is still produced but the gap is visible.

    elapsed_pct            days since start / planned duration x 100 (over 100 once past the planned end)
    planned_duration_days  start to planned end, inclusive
    progress_gap_pct       actual minus planned progress today, percentage points
    progress_rate_trend    change in that gap per week over the last three weeks
    late_deliveries_count  order lines delivered after, or still overdue past, their expected date
    avg_lateness_days      mean lateness of those lines
    rain_days_next_14      forecast days with heavy rain (BR-06: 10 mm or more) in the next 14 days
    wet_days_ahead         heavy-rain working days expected from the site's climate (in Sri Lanka the
                           nearest of seven towns, elsewhere the site's own history; climate.for_site)
                           from tomorrow to the planned end, at least the next 28 days (1.2)
    budget_variance_pct    committed cost against the budgeted value of the same work, % over
    crew_vs_plan_pct       average reported crew over the last 14 days against the planned crew, %
    missing_reports_14     working days (Mon to Sat) in the last 14 without a daily report (BR-07)
    issues_*_14            confirmed material-delay, safety and design issues in the last 14 days of
                           reports (Phase 7: tagged by the report classifier, confirmed by the author)
    contract_value_m       LKR millions: the contract value converted with SITESENSE_RISK_LKR_PER_UNIT
                           when the company's currency is not LKR (the model was trained in LKR)
    type_*                 project type, one-hot
"""

from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.risk import climate
from app.core import company
from app.models import (
    DailyReport,
    Delivery,
    IssueStatus,
    ProgressSnapshot,
    Project,
    PurchaseOrder,
    PurchaseOrderLine,
    ReportIssue,
    Task,
    WeatherForecast,
)
from app.services.materials_service import committed_against_budget
from app.services.progress import TaskPlan, actual_percent, planned_percent

PROJECT_TYPES = ("residential", "commercial", "mixed_use", "industrial", "institutional")
FEATURE_NAMES = (
    "elapsed_pct",
    "planned_duration_days",
    "progress_gap_pct",
    "progress_rate_trend",
    "late_deliveries_count",
    "avg_lateness_days",
    "rain_days_next_14",
    "wet_days_ahead",
    "budget_variance_pct",
    "crew_vs_plan_pct",
    "missing_reports_14",
    "issues_material_14",
    "issues_safety_14",
    "issues_design_14",
    "contract_value_m",
    *(f"type_{t}" for t in PROJECT_TYPES),
)
HEAVY_RAIN_MM = Decimal(10)
TREND_WEEKS = 3
WINDOW_DAYS = 14
FORECAST_DAYS = 14


@dataclass
class FeatureSet:
    values: dict[str, float]
    notes: list[str] = field(default_factory=list)  # what was missing, in words

    def vector(self) -> tuple[float, ...]:
        return tuple(self.values[name] for name in FEATURE_NAMES)


def _working_days(start: date, end: date) -> list[date]:
    """Monday to Saturday from start to end, inclusive."""
    days = []
    current = start
    while current <= end:
        if current.weekday() < 6:
            days.append(current)
        current += timedelta(days=1)
    return days


def _progress(db: Session, project: Project, on: date, notes: list[str]) -> tuple[float, float]:
    """(progress gap now, its weekly trend over the last three weeks)."""
    tasks = db.scalars(select(Task).where(Task.project_id == project.id)).all()
    if not tasks:
        notes.append("No programme yet: progress counts as on plan.")
        return 0.0, 0.0
    plans = [TaskPlan(t.planned_start, t.planned_end, t.weight, t.percent_complete) for t in tasks]
    gap_now = actual_percent(plans) - planned_percent(plans, on)
    weeks = min(TREND_WEEKS, max((on - project.start_date).days // 7, 0))
    if weeks == 0:
        return gap_now, 0.0
    then = on - timedelta(weeks=weeks)
    history = sorted(
        (row.snapshot_date, float(row.actual_percent))
        for row in db.scalars(
            select(ProgressSnapshot).where(
                ProgressSnapshot.project_id == project.id, ProgressSnapshot.snapshot_date <= then
            )
        )
    )
    index = bisect_right([d for d, _ in history], then)
    actual_then = history[index - 1][1] if index else 0.0
    gap_then = actual_then - planned_percent(plans, then)
    return gap_now, (gap_now - gap_then) / weeks


def _deliveries(db: Session, project: Project, on: date) -> tuple[float, float]:
    """(late or overdue order lines, their mean lateness in days), for lines due by ``on``."""
    lines = db.execute(
        select(PurchaseOrderLine.id, PurchaseOrderLine.quantity, PurchaseOrder.expected_delivery)
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(PurchaseOrder.project_id == project.id, PurchaseOrder.expected_delivery <= on)
    ).all()
    if not lines:
        return 0.0, 0.0
    deliveries: dict[object, list[tuple[date, Decimal]]] = {}
    for line_id, qty, delivered_on in db.execute(
        select(Delivery.line_id, Delivery.quantity, Delivery.delivered_on).where(
            Delivery.line_id.in_([line.id for line in lines]), Delivery.delivered_on <= on
        )
    ):
        deliveries.setdefault(line_id, []).append((delivered_on, qty))
    lateness: list[int] = []
    for line_id, quantity, expected in lines:
        received = Decimal(0)
        completed: date | None = None
        for delivered_on, qty in sorted(deliveries.get(line_id, [])):
            received += qty
            if received >= quantity:
                completed = delivered_on
                break
        days = ((completed or on) - expected).days
        if days > 0:
            lateness.append(days)
    return float(len(lateness)), (sum(lateness) / len(lateness)) if lateness else 0.0


def _rain(db: Session, project: Project, on: date, notes: list[str]) -> float:
    rows = db.scalars(
        select(WeatherForecast.rain_mm).where(
            WeatherForecast.site_id == project.site_id,
            WeatherForecast.forecast_date > on,
            WeatherForecast.forecast_date <= on + timedelta(days=FORECAST_DAYS),
        )
    ).all()
    if not rows:
        notes.append("No weather forecast cached: rain counts as none.")
        return 0.0
    heavy = sum(1 for mm in rows if mm is not None and mm >= HEAVY_RAIN_MM)
    if len(rows) < FORECAST_DAYS:
        notes.append(f"Only {len(rows)} forecast days cached: rain scaled to 14 days.")
    return heavy * FORECAST_DAYS / len(rows)


def _wet_days_ahead(project: Project, on: date, notes: list[str]) -> float:
    site = project.site
    choice = climate.for_site(site.latitude, site.longitude, site.rain_climate)
    if choice.note:
        notes.append(choice.note)
    return climate.wet_days_ahead(choice.town, on, project.planned_end)


def _cost(db: Session, project: Project) -> float:
    committed, budgeted = committed_against_budget(db, project.id)
    if budgeted <= 0:
        return 0.0
    return float((committed - budgeted) / budgeted * 100)


def _reports(db: Session, project: Project, on: date, notes: list[str]) -> tuple[float, float]:
    """(crew against plan %, missing reports) over the last 14 days."""
    since = max(on - timedelta(days=WINDOW_DAYS - 1), project.start_date)
    if since > on:
        return 0.0, 0.0
    reports = db.execute(
        select(DailyReport.report_date, DailyReport.crew_count).where(
            DailyReport.project_id == project.id,
            DailyReport.report_date >= since,
            DailyReport.report_date <= on,
        )
    ).all()
    filed = {day for day, _ in reports}
    missing = sum(1 for day in _working_days(since, on) if day not in filed)
    if not project.planned_crew:
        notes.append("No planned crew size set: crew counts as on plan.")
        return 0.0, float(missing)
    if not reports:
        return 0.0, float(missing)
    average = sum(crew for _, crew in reports) / len(reports)
    return (average / project.planned_crew - 1) * 100, float(missing)


def _issues(db: Session, project: Project, on: date) -> dict[str, float]:
    """Confirmed issues by category in reports dated within the last 14 days."""
    since = on - timedelta(days=WINDOW_DAYS - 1)
    counts = dict(
        db.execute(
            select(ReportIssue.category, func.count(ReportIssue.id))
            .join(DailyReport, DailyReport.id == ReportIssue.report_id)
            .where(
                ReportIssue.project_id == project.id,
                ReportIssue.status == IssueStatus.CONFIRMED.value,
                DailyReport.report_date >= since,
                DailyReport.report_date <= on,
            )
            .group_by(ReportIssue.category)
        ).all()
    )
    return {
        "issues_material_14": float(counts.get("material_delay", 0)),
        "issues_safety_14": float(counts.get("safety", 0)),
        "issues_design_14": float(counts.get("design", 0)),
    }


def contract_value_m(value: Decimal) -> float:
    """The contract value in millions of Sri Lankan rupees, the unit the model was trained on."""
    return float(value * company.current().lkr_per_unit) / 1_000_000


def build(db: Session, project: Project, on: date) -> FeatureSet:
    notes: list[str] = []
    planned_days = (project.planned_end - project.start_date).days + 1
    started = on >= project.start_date
    elapsed = max((on - project.start_date).days + 1, 0) / planned_days * 100 if planned_days > 0 else 0.0
    if started:
        gap, trend = _progress(db, project, on, notes)
        crew, missing = _reports(db, project, on, notes)
    else:
        notes.append("Not started yet: the score rests on the project's size and type.")
        gap = trend = crew = missing = 0.0
    late_count, lateness = _deliveries(db, project, on)
    values = {
        "elapsed_pct": elapsed,
        "planned_duration_days": float(planned_days),
        "progress_gap_pct": gap,
        "progress_rate_trend": trend,
        "late_deliveries_count": late_count,
        "avg_lateness_days": lateness,
        "rain_days_next_14": _rain(db, project, on, notes),
        "wet_days_ahead": _wet_days_ahead(project, on, notes),
        "budget_variance_pct": _cost(db, project),
        "crew_vs_plan_pct": crew,
        "missing_reports_14": missing,
        **_issues(db, project, on),
        "contract_value_m": contract_value_m(project.contract_value),
        **{f"type_{t}": float(project.project_type == t) for t in PROJECT_TYPES},
    }
    return FeatureSet({k: round(v, 4) for k, v in values.items()}, notes)
