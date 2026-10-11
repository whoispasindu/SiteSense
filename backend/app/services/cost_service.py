"""Cost control (Phase 8): forecast final cost per BOQ section, variance alerts, section contract values.

The forecast method is in ``app.rules.cost``. Variance alerts work like the BR-10 risk alert: when a
section's forecast first goes more than 5% over its budget, the site's project managers and quantity
surveyors are notified once (``budget_lines.over_budget_since`` remembers it); coming back under
clears it, so a later overrun alerts again. Checked every morning, after cost-changing events
(approvals, orders, deliveries, variations), and with ``python -m app.cli check-variance``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.logging import get_logger
from app.core.permissions import Permission, Role, has_permission
from app.core.scoping import scope_to_user_sites
from app.models import (
    BoqItem,
    BoqSection,
    BudgetLine,
    ClaimStatus,
    ProgressClaim,
    Project,
    ProjectStatus,
    User,
    VariationOrder,
)
from app.rules import cost as rules
from app.rules.materials import ZERO, money
from app.rules.variations import OPEN_STATUSES, VariationStatus
from app.schemas.contract import CostOverview, ProjectCostOut, WaitingItem
from app.services import notification_service
from app.services.materials_service import committed_against_budget_by_section, section_costs
from app.services.notification_service import NewNotification

log = get_logger(__name__)

CHECKED_STATUSES = (ProjectStatus.ACTIVE.value, ProjectStatus.ON_HOLD.value)


def section_contract_values(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, Decimal]:
    """Each section's contract value: its BOQ amount plus the contract change of approved variations."""
    boq = dict(
        db.execute(
            select(BoqSection.id, func.coalesce(func.sum(BoqItem.amount), 0))
            .outerjoin(BoqItem, BoqItem.section_id == BoqSection.id)
            .where(BoqSection.project_id == project_id)
            .group_by(BoqSection.id)
        ).all()
    )
    varied = dict(
        db.execute(
            select(VariationOrder.section_id, func.sum(VariationOrder.contract_change))
            .where(
                VariationOrder.project_id == project_id,
                VariationOrder.status == VariationStatus.APPROVED.value,
            )
            .group_by(VariationOrder.section_id)
        ).all()
    )
    return {
        section_id: max(Decimal(amount) + Decimal(varied.get(section_id) or 0), ZERO)
        for section_id, amount in boq.items()
    }


def forecasts(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, rules.Forecast]:
    """The forecast for every section that has a budget line."""
    costs = section_costs(db, project_id)
    against = committed_against_budget_by_section(db, project_id)
    lines = db.execute(
        select(BudgetLine.section_id, BudgetLine.budget_amount).where(BudgetLine.project_id == project_id)
    ).all()
    out = {}
    for section_id, budget in lines:
        _, budgeted = against.get(section_id, (ZERO, ZERO))
        committed = costs[section_id].committed if section_id in costs else ZERO
        out[section_id] = rules.forecast_final_cost(
            budget=Decimal(budget), committed=committed, committed_budget_value=budgeted
        )
    return out


# --- Variance alerts ------------------------------------------------------------------------------------


def check_variance(db: Session, project: Project, on: date | None = None) -> list[BoqSection]:
    """Alert on sections whose forecast has just gone over the alert line. Returns those sections.

    The caller commits. Projects that are not active or on hold are left alone.
    """
    if project.status not in CHECKED_STATUSES:
        return []
    on = on or clock.site_today()
    by_section = forecasts(db, project.id)
    lines = db.scalars(select(BudgetLine).where(BudgetLine.project_id == project.id).with_for_update()).all()
    newly_over = []
    for line in lines:
        forecast = by_section.get(line.section_id)
        if forecast is None:
            continue
        if forecast.over_alert_line and line.over_budget_since is None:
            line.over_budget_since = on
            newly_over.append((line, forecast))
        elif not forecast.over_alert_line and line.over_budget_since is not None:
            line.over_budget_since = None
    if newly_over:
        _alert(db, project, newly_over, on)
    return [line.section for line, _ in newly_over]


def _alert(db: Session, project: Project, over: list[tuple[BudgetLine, rules.Forecast]], on: date) -> None:
    people = notification_service.site_people(
        db, project.site_id, {Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR}
    )
    items: list[NewNotification] = []
    for line, forecast in over:
        share = -(forecast.variance_share or ZERO)
        percent = f"{(share * 100).quantize(Decimal('0.1'))}%" if forecast.variance_share is not None else ""
        body = (
            f"{line.section.code} {line.section.name} is forecast to finish at "
            f"LKR {forecast.final_cost:,.0f} against a budget of LKR {forecast.budget:,.0f}"
            + (f" ({percent} over)." if percent else ".")
        )
        items.extend(
            NewNotification(
                user_id=person.id,
                kind="cost_variance",
                title=f"Forecast overrun on {project.code}",
                body=body,
                link=f"/projects/{project.id}/budget",
                project_id=project.id,
                dedupe_key=f"variance:{line.id}:{on.isoformat()}",
            )
            for person in people
        )
    notification_service.send(db, items)


def check_after_change(db: Session, project: Project) -> None:
    """Best effort after a cost-changing event: the event itself is never undone by a failure here."""
    try:
        check_variance(db, project)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("variance_check_failed", project=project.code)


def check_all(db: Session, on: date | None = None) -> int:
    """The daily check over every active or on-hold project. Returns the number of new alerts."""
    alerts = 0
    projects = db.scalars(select(Project).where(Project.status.in_(CHECKED_STATUSES)).order_by(Project.code))
    for project in projects.all():
        try:
            alerts += len(check_variance(db, project, on))
            db.commit()
        except Exception:
            db.rollback()
            log.exception("variance_check_failed", project=project.code)
    log.info("variance_checked", alerts=alerts)
    return alerts


# --- Portfolio overview ---------------------------------------------------------------------------------


def overview(db: Session, user: User) -> CostOverview:
    """Every project on the user's sites: contract, budget, forecast, claims and open variations."""
    can_price = has_permission(Role(user.role), Permission.VARIATIONS_PRICE)
    can_approve = has_permission(Role(user.role), Permission.VARIATIONS_APPROVE)
    can_approve_claims = has_permission(Role(user.role), Permission.CLAIMS_APPROVE)
    projects = db.scalars(
        scope_to_user_sites(select(Project).order_by(Project.code), Project.site_id, user)
    ).all()
    rows: list[ProjectCostOut] = []
    waiting: list[WaitingItem] = []
    for project in projects:
        by_section = forecasts(db, project.id)
        committed = sum((c.committed for c in section_costs(db, project.id).values()), ZERO)
        budget = sum((f.budget for f in by_section.values()), ZERO)
        final = sum((f.final_cost for f in by_section.values()), ZERO)
        claims = db.scalars(select(ProgressClaim).where(ProgressClaim.project_id == project.id)).all()
        variations = db.scalars(select(VariationOrder).where(VariationOrder.project_id == project.id)).all()
        open_claim = next((c for c in claims if c.status == ClaimStatus.SUBMITTED.value), None)
        rows.append(
            ProjectCostOut(
                project_id=project.id,
                code=project.code,
                name=project.name,
                status=project.status,
                contract_value=project.contract_value,
                approved_variations=money(
                    sum(
                        (
                            v.contract_change or ZERO
                            for v in variations
                            if v.status == VariationStatus.APPROVED
                        ),
                        ZERO,
                    )
                ),
                budget=money(budget),
                committed=money(committed),
                forecast_final=money(final),
                variance=money(budget - final),
                variance_pct=((budget - final) / budget * 100).quantize(Decimal("0.1"))
                if budget > ZERO
                else None,
                sections_over=sum(1 for f in by_section.values() if f.over_alert_line),
                claimed_to_date=money(
                    sum(
                        (c.amount for c in claims if c.status in (ClaimStatus.APPROVED, ClaimStatus.PAID)),
                        ZERO,
                    )
                ),
                open_claim=open_claim.number if open_claim else None,
                variations_open=sum(1 for v in variations if v.status in OPEN_STATUSES),
            )
        )
        if open_claim is not None and can_approve_claims:
            waiting.append(
                WaitingItem(kind="claim", id=open_claim.id, number=open_claim.number, project_id=project.id,
                            project_code=project.code, title=f"Claim of LKR {open_claim.amount:,.2f}",
                            status=open_claim.status, since=open_claim.submitted_at)
            )  # fmt: skip
        for v in variations:
            mine = (v.status == VariationStatus.AWAITING_PRICING and can_price) or (
                v.status == VariationStatus.AWAITING_PM and can_approve and v.raised_by != user.id
            )
            if mine:
                waiting.append(
                    WaitingItem(kind="variation", id=v.id, number=v.number, project_id=project.id,
                                project_code=project.code, title=v.title, status=v.status, since=v.raised_at)
                )  # fmt: skip
    waiting.sort(key=lambda item: item.since)
    return CostOverview(projects=rows, waiting_for_you=waiting)
