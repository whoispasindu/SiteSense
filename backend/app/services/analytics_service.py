"""Portfolio analytics (Phase 11): one call for the dashboard, scoped to the user's sites (BR-03).

KPIs, cost against plan (with the risk model's likely range), the risk ranking, issue trends, the
5-day weather for each site and the approval queue. Sections follow the reader's permissions:
cost only with ``cost:read``, risk only with ``risk:read``. The arithmetic is in ``app.rules.kpis``.

Weather comes from the saved forecast (refreshed every morning), so the dashboard never waits on
the weather service.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.permissions import Permission, Role, has_permission
from app.core.scoping import scope_to_user_sites
from app.models import (
    ActionKind,
    ActionStatus,
    DailyReport,
    IssueCategory,
    IssueStatus,
    MaterialRequest,
    ProgressClaim,
    Project,
    ProjectStatus,
    ReportAction,
    ReportIssue,
    Site,
    User,
    VariationOrder,
    WeatherForecast,
)
from app.models.contract import ClaimStatus
from app.rules import kpis
from app.rules import materials as material_rules
from app.rules.variations import VariationStatus
from app.schemas.analytics import (
    ApprovalItem,
    CostAgainstPlan,
    CostTotalsOut,
    IssueWeek,
    Kpis,
    Portfolio,
    ProjectCostPoint,
    RangeLKR,
    SiteWeather,
)
from app.schemas.report import WeatherDayOut
from app.schemas.risk import RiskRanking
from app.services import (
    cost_service,
    handover_service,
    materials_service,
    risk_service,
    schedule_service,
)

OPEN_STATUSES = (ProjectStatus.ACTIVE.value, ProjectStatus.ON_HOLD.value)
HEAVY_RAIN_MM = Decimal("10.0")  # BR-06
WEATHER_DAYS = 5
WEATHER_STALE_AFTER = timedelta(hours=30)  # refreshed at 05:30 each day; older means a missed refresh
APPROVALS_LIMIT = 20


def _can(user: User, permission: Permission) -> bool:
    return has_permission(Role(user.role), permission)


def scoped_projects(db: Session, user: User) -> list[Project]:
    return list(
        db.scalars(scope_to_user_sites(select(Project).order_by(Project.code), Project.site_id, user))
    )


# --- KPIs -------------------------------------------------------------------------------------------------


def _reports_today(db: Session, projects: list[Project], today: date) -> tuple[int, int]:
    due = [p.id for p in projects if p.status == ProjectStatus.ACTIVE.value and p.start_date <= today]
    if not due:
        return 0, 0
    filed = db.scalar(
        select(func.count(DailyReport.id)).where(
            DailyReport.project_id.in_(due), DailyReport.report_date == today
        )
    )
    return len(due), int(filed or 0)


def confirmed_issues(
    db: Session, project_ids: list[uuid.UUID], since: date
) -> list[tuple[date, str, uuid.UUID]]:
    """(report date, category, project) of every confirmed issue in reports from ``since``."""
    if not project_ids:
        return []
    rows = db.execute(
        select(DailyReport.report_date, ReportIssue.category, ReportIssue.project_id)
        .join(DailyReport, DailyReport.id == ReportIssue.report_id)
        .where(
            ReportIssue.project_id.in_(project_ids),
            ReportIssue.status == IssueStatus.CONFIRMED.value,
            DailyReport.report_date >= since,
        )
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def open_stop_work(db: Session, project_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not project_ids:
        return {}
    rows = db.execute(
        select(ReportAction.project_id, func.count(ReportAction.id))
        .where(
            ReportAction.project_id.in_(project_ids),
            ReportAction.kind == ActionKind.STOP_WORK.value,
            ReportAction.status == ActionStatus.OPEN.value,
        )
        .group_by(ReportAction.project_id)
    ).all()
    return {r[0]: int(r[1]) for r in rows}


# --- Cost against plan ------------------------------------------------------------------------------------


def project_costs(db: Session, project: Project) -> tuple[Decimal, Decimal, Decimal]:
    """(budget, committed, forecast final at current rates), from the cost rules (Phase 8)."""
    by_section = cost_service.forecasts(db, project.id)
    committed = sum(
        (c.committed for c in materials_service.section_costs(db, project.id).values()), Decimal(0)
    )
    budget = sum((f.budget for f in by_section.values()), Decimal(0))
    final = sum((f.final_cost for f in by_section.values()), Decimal(0))
    return budget, committed, final


def _cost(db: Session, projects: list[Project], ranking: dict[uuid.UUID, RiskRanking]) -> CostAgainstPlan:
    points: list[ProjectCostPoint] = []
    for p in projects:
        if p.status not in OPEN_STATUSES:
            continue
        budget, committed, final = project_costs(db, p)
        risk = ranking.get(p.id)
        model_range = None
        if risk is not None and risk.ranges is not None and budget > 0:
            low, high = kpis.final_cost_range(
                budget, risk.ranges.overrun_pct.low, risk.ranges.overrun_pct.high
            )
            model_range = RangeLKR(low=low, high=high)
        points.append(
            ProjectCostPoint(
                project_id=p.id,
                code=p.code,
                name=p.name,
                budget=budget,
                committed=committed,
                forecast_final=final,
                model_final_range=model_range,
            )
        )
    totals = kpis.cost_totals((pt.budget, pt.committed, pt.forecast_final) for pt in points)
    return CostAgainstPlan(
        totals=CostTotalsOut(
            budget=totals.budget,
            committed=totals.committed,
            forecast_final=totals.forecast_final,
            over_budget=totals.over_budget,
        ),
        projects=points,
    )


# --- Weather ----------------------------------------------------------------------------------------------


def site_weather(db: Session, projects: list[Project], today: date) -> list[SiteWeather]:
    sites: dict[uuid.UUID, Site] = {}
    for p in projects:
        if p.status in OPEN_STATUSES and p.site.is_active:
            sites.setdefault(p.site_id, p.site)
    out: list[SiteWeather] = []
    now = clock.utcnow()
    for site in sorted(sites.values(), key=lambda s: s.code):
        rows = db.scalars(
            select(WeatherForecast)
            .where(WeatherForecast.site_id == site.id, WeatherForecast.forecast_date >= today)
            .order_by(WeatherForecast.forecast_date)
            .limit(WEATHER_DAYS)
        ).all()
        fetched = min((r.fetched_at for r in rows), default=None)
        out.append(
            SiteWeather(
                site_code=site.code,
                site_name=site.name,
                available=bool(rows),
                stale=fetched is not None and now - fetched > WEATHER_STALE_AFTER,
                fetched_at=fetched,
                days=[
                    WeatherDayOut(
                        date=r.forecast_date,
                        summary=r.summary,
                        weather_code=r.weather_code,
                        temp_max_c=r.temp_max_c,
                        temp_min_c=r.temp_min_c,
                        rain_mm=r.rain_mm,
                        rain_probability=r.rain_probability,
                    )
                    for r in rows
                ],
                heavy_rain_threshold_mm=HEAVY_RAIN_MM,
            )
        )
    return out


# --- The approval queue -----------------------------------------------------------------------------------


def approvals(db: Session, user: User, projects: list[Project]) -> list[ApprovalItem]:
    """What is waiting for this user to act on, oldest first.

    Material requests at the reader's approval stage (never their own), requests ready to order for
    procurement, submitted claims for the PM, and variations to price (QS) or decide (PM, not their own).
    Titles carry no amounts: the queue is the same for every role that can see it.
    """
    by_id = {p.id: p for p in projects}
    if not by_id:
        return []
    ids = list(by_id)
    items: list[ApprovalItem] = []

    stages: set[material_rules.Stage] = set()
    if _can(user, Permission.MATERIALS_APPROVE_QS):
        stages.add("qs")
    if _can(user, Permission.MATERIALS_APPROVE_PM):
        stages.add("pm")
    statuses = material_rules.statuses_at(stages)
    ordering = _can(user, Permission.PURCHASE_ORDERS_MANAGE)
    if ordering:
        statuses.append("approved")
    if statuses:
        for r in db.scalars(
            select(MaterialRequest).where(
                MaterialRequest.project_id.in_(ids),
                MaterialRequest.status.in_(statuses),
                MaterialRequest.requested_by != user.id,
            )
        ).all():
            ready = r.status == "approved"
            items.append(
                ApprovalItem(
                    kind="purchase_order" if ready else "material_request",
                    id=r.id,
                    number=r.number,
                    project_id=r.project_id,
                    project_code=by_id[r.project_id].code,
                    title=("Ready to order: " if ready else "") + r.boq_item.description[:120],
                    status=r.status,
                    since=r.submitted_at,
                    link=f"/materials/{r.id}",
                )
            )

    if _can(user, Permission.CLAIMS_APPROVE):
        for c in db.scalars(
            select(ProgressClaim).where(
                ProgressClaim.project_id.in_(ids), ProgressClaim.status == ClaimStatus.SUBMITTED.value
            )
        ).all():
            items.append(
                ApprovalItem(
                    kind="claim",
                    id=c.id,
                    number=c.number,
                    project_id=c.project_id,
                    project_code=by_id[c.project_id].code,
                    title=f"Progress claim {c.number}",
                    status=c.status,
                    since=c.submitted_at,
                    link=f"/projects/{c.project_id}/claims",
                )
            )

    can_price = _can(user, Permission.VARIATIONS_PRICE)
    can_decide = _can(user, Permission.VARIATIONS_APPROVE)
    if can_price or can_decide:
        wanted = [VariationStatus.AWAITING_PRICING.value] if can_price else []
        wanted += [VariationStatus.AWAITING_PM.value] if can_decide else []
        for v in db.scalars(
            select(VariationOrder).where(
                VariationOrder.project_id.in_(ids), VariationOrder.status.in_(wanted)
            )
        ).all():
            if v.status == VariationStatus.AWAITING_PM.value and v.raised_by == user.id:
                continue  # nobody decides their own variation
            items.append(
                ApprovalItem(
                    kind="variation",
                    id=v.id,
                    number=v.number,
                    project_id=v.project_id,
                    project_code=by_id[v.project_id].code,
                    title=v.title,
                    status=v.status,
                    since=v.raised_at,
                    link=f"/variations/{v.id}",
                )
            )
    items.sort(key=lambda item: item.since)
    return items


# --- The whole dashboard ----------------------------------------------------------------------------------


def portfolio(db: Session, user: User) -> Portfolio:
    today = clock.site_today()
    projects = scoped_projects(db, user)
    open_ids = [p.id for p in projects if p.status in OPEN_STATUSES]
    sees_risk = _can(user, Permission.RISK_READ)
    sees_cost = _can(user, Permission.COST_READ)

    summaries = [s for s in schedule_service.summaries(db, user) if s.project.status in OPEN_STATUSES]
    progress = kpis.progress_kpis(
        kpis.Progress(s.planned_percent, s.actual_percent, s.task_count) for s in summaries
    )
    due, filed = _reports_today(db, projects, today)
    weeks = kpis.trend_weeks(today)
    issues = confirmed_issues(db, open_ids, weeks[0])
    trend = kpis.issue_trend(((d, c) for d, c, _ in issues), today, [c.value for c in IssueCategory])
    ranking = risk_service.ranking(db, user) if sees_risk else None
    queue = approvals(db, user, projects)

    return Portfolio(
        as_of=today,
        kpis=Kpis(
            active_projects=sum(1 for p in projects if p.status == ProjectStatus.ACTIVE.value),
            total_projects=len(projects),
            average_actual_pct=progress.average_actual,
            average_planned_pct=progress.average_planned,
            behind_plan=progress.behind_plan,
            reports_due_today=due,
            reports_filed_today=filed,
            issues_this_week=sum(trend[-1][1].values()),
            stop_work_open=sum(open_stop_work(db, open_ids).values()),
            waiting_for_you=len(queue),
            high_risk=sum(1 for r in ranking if r.level == "high") if ranking is not None else None,
        ),
        cost=_cost(db, projects, {r.project_id: r for r in ranking or []}) if sees_cost else None,
        risk=ranking,
        issue_trend=[
            IssueWeek(week_start=start, total=sum(counts.values()), by_category=counts)
            for start, counts in trend
        ],
        weather=site_weather(db, projects, today),
        approvals=queue[:APPROVALS_LIMIT],
        handover_reminders=handover_service.reminders(db, user)
        if _can(user, Permission.PROJECTS_MANAGE)
        else None,
    )
