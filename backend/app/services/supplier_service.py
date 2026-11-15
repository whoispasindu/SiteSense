"""Supplier on-time estimates and BR-12 (Phase 10).

BR-12: if a supplier's predicted on-time chance is under 50% for a critical-path item, suggest an
alternative. A request is a critical-path item when the project manager says so, or, by default,
when its BOQ item's section is linked to a programme task that is critical or has
``br12_float_days`` working days of float or fewer (Phase 9 network).

A supplier's record is company-wide: every order line already due, on time if its whole quantity had
arrived by the expected date (the same rule as the risk model's late deliveries). The estimate shows
how many deliveries it rests on, and a likely range that is wide when there are few.
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.risk import climate
from app.ai.supplier import model as supplier_model
from app.core import clock
from app.core.config import get_settings
from app.core.errors import ForbiddenError, NotFoundError
from app.core.permissions import Role
from app.models import (
    BoqItem,
    Delivery,
    MaterialRequest,
    Project,
    PurchaseOrder,
    PurchaseOrderLine,
    RequestStatus,
    Supplier,
    Task,
    User,
)
from app.schemas.supplier import ChanceRange, CriticalPathIn, CriticalPathOut, OnTimeOut, OutlookOut
from app.services import audit, materials_service, network_service, project_service
from app.services.audit import AuditAction, RequestMeta

THRESHOLD = 0.5  # BR-12
Z_80 = 1.2816  # the 10th and 90th percentiles of a normal distribution
MODEL_WORDS = {"smoothed": "smoothed on-time rate", "logistic": "logistic regression"}


@dataclass(frozen=True, slots=True)
class Record:
    on_time: int
    count: int


def records(db: Session, today: date) -> tuple[dict[uuid.UUID, Record], Record]:
    """Each supplier's record, and the company's, from order lines due before ``today``."""
    lines = db.execute(
        select(
            PurchaseOrderLine.id,
            PurchaseOrderLine.quantity,
            PurchaseOrder.supplier_id,
            PurchaseOrder.expected_delivery,
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.purchase_order_id)
        .where(PurchaseOrder.expected_delivery < today)
    ).all()
    if not lines:
        return {}, Record(0, 0)
    arrived: dict[uuid.UUID, list[tuple[date, Decimal]]] = {}
    for line_id, quantity, delivered_on in db.execute(
        select(Delivery.line_id, Delivery.quantity, Delivery.delivered_on).where(
            Delivery.line_id.in_([line.id for line in lines])
        )
    ):
        arrived.setdefault(line_id, []).append((delivered_on, quantity))
    per_supplier: dict[uuid.UUID, list[int]] = {}
    for line_id, quantity, supplier_id, expected in lines:
        received = Decimal(0)
        completed: date | None = None
        for delivered_on, qty in sorted(arrived.get(line_id, [])):
            received += qty
            if received >= quantity:
                completed = delivered_on
                break
        on_time = completed is not None and completed <= expected
        tally = per_supplier.setdefault(supplier_id, [0, 0])
        tally[0] += int(on_time)
        tally[1] += 1
    company = Record(sum(t[0] for t in per_supplier.values()), sum(t[1] for t in per_supplier.values()))
    return {s: Record(t[0], t[1]) for s, t in per_supplier.items()}, company


def _wet_share(project: Project | None, expected: date) -> float:
    if project is None:
        town = climate.national_average()
    else:
        site = project.site
        town = climate.for_site(site.latitude, site.longitude, site.rain_climate).town
    return town.heavy_day_share[expected.month - 1]


def estimate(
    supplier: Supplier, record: Record, company: Record, *, lead_time_days: int, wet_share: float
) -> OnTimeOut:
    model = supplier_model.current()
    inputs = model.inputs(
        supplier_on_time=record.on_time,
        supplier_count=record.count,
        company_on_time=company.on_time,
        company_count=company.count,
        lead_time_days=lead_time_days,
        wet_share=wet_share,
    )
    chance = model.chance(inputs)
    # Likely range: on the log-odds scale, as if the chance rested on the supplier's deliveries plus the
    # smoothing's pseudo-deliveries. Wide with little history, narrowing as deliveries are recorded.
    effective = record.count + model.prior_strength
    spread = Z_80 / math.sqrt(effective * chance * (1 - chance))
    centre = supplier_model.logit(chance)
    return OnTimeOut(
        supplier_id=supplier.id,
        supplier_name=supplier.name,
        chance=round(chance, 3),
        chance_range=ChanceRange(
            low=round(supplier_model.sigmoid(centre - spread), 3),
            high=round(supplier_model.sigmoid(centre + spread), 3),
        ),
        based_on=record.count,
        low_data=record.count < model.low_data_deliveries,
        below_br12=chance < THRESHOLD,
        model=MODEL_WORDS[model.kind],
        model_version=model.version,
    )


def on_time(
    db: Session, user: User, supplier_id: uuid.UUID, project_id: uuid.UUID | None, expected: date | None
) -> OnTimeOut:
    """GET /suppliers/{id}/on-time: the supplier's chance, for an order on a project if given."""
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundError("Supplier not found.")
    project = project_service.get_project(db, user, project_id) if project_id else None
    today = clock.site_today()
    expected = expected or today
    per_supplier, company = records(db, today)
    return estimate(
        supplier,
        per_supplier.get(supplier.id, Record(0, 0)),
        company,
        lead_time_days=max((expected - today).days, 0),
        wet_share=_wet_share(project, expected),
    )


# --- BR-12: critical-path items ------------------------------------------------------------------------


def _near_critical_sections(db: Session, project: Project) -> dict[uuid.UUID, str]:
    """BOQ sections linked to a critical or near-critical unfinished task, with the reason in words."""
    float_days = get_settings().br12_float_days
    network = network_service.analyse(db, project)
    sections = dict(
        db.execute(select(Task.id, Task.boq_section_id).where(Task.project_id == project.id)).all()
    )
    out: dict[uuid.UUID, str] = {}
    for t in network.tasks:
        section = sections.get(t.task_id)
        if section is None or t.is_done or section in out:
            continue
        label = t.code or t.name
        if t.is_critical:
            out[section] = f"Linked to {label}, a critical task."
        elif t.total_float <= float_days:
            days = "working day" if t.total_float == 1 else "working days"
            out[section] = f"Linked to {label}, which has {t.total_float} {days} of float."
    return out


def _critical(request: MaterialRequest, sections: dict[uuid.UUID, str]) -> tuple[bool, bool, str]:
    """(counts for BR-12, what the programme says, reason)."""
    from_programme = request.boq_item.section_id in sections
    if request.critical_override is not None:
        who = "Marked critical" if request.critical_override else "Marked not critical"
        return request.critical_override, from_programme, f"{who} by the project manager."
    if from_programme:
        return True, True, sections[request.boq_item.section_id]
    return False, False, "No critical or near-critical task is linked to this item's BOQ section."


def _critical_out(user: User, request: MaterialRequest, sections: dict[uuid.UUID, str]) -> CriticalPathOut:
    critical, from_programme, reason = _critical(request, sections)
    return CriticalPathOut(
        request_id=request.id,
        critical=critical,
        from_programme=from_programme,
        override=request.critical_override,
        reason=reason,
        can_override=user.role == Role.PROJECT_MANAGER.value,
        float_days=get_settings().br12_float_days,
    )


def critical_path(db: Session, user: User, request_id: uuid.UUID) -> CriticalPathOut:
    request = materials_service.get_request(db, user, request_id)  # 404 outside the user's sites
    return _critical_out(user, request, _near_critical_sections(db, request.project))


def set_critical_path(
    db: Session, user: User, request_id: uuid.UUID, data: CriticalPathIn, *, meta: RequestMeta
) -> CriticalPathOut:
    """The project manager marks a request critical or not, or hands it back to the programme. Audited."""
    if user.role != Role.PROJECT_MANAGER.value:  # before the lookup: says nothing about the request
        raise ForbiddenError("Only the project manager marks a request as a critical-path item.")
    request = materials_service.get_request(db, user, request_id, lock=True)
    before = request.critical_override
    request.critical_override = data.critical
    audit.record(
        db,
        AuditAction.CRITICAL_PATH_OVERRIDE,
        meta=meta,
        actor_id=user.id,
        target_type="material_request",
        target_id=request.id,
        details={"number": request.number, "before": before, "after": data.critical},
    )
    db.commit()
    return _critical_out(user, request, _near_critical_sections(db, request.project))


def outlook(db: Session, user: User, project_id: uuid.UUID, expected: date | None) -> OutlookOut:
    """Every active supplier's chance for an order on this project due on ``expected``, best first."""
    project = project_service.get_project(db, user, project_id)  # 404 outside the user's sites
    today = clock.site_today()
    expected = expected or today
    per_supplier, company = records(db, today)
    lead = max((expected - today).days, 0)
    wet = _wet_share(project, expected)
    suppliers = db.scalars(select(Supplier).where(Supplier.is_active.is_(True)).order_by(Supplier.name)).all()
    estimates = [
        estimate(s, per_supplier.get(s.id, Record(0, 0)), company, lead_time_days=lead, wet_share=wet)
        for s in suppliers
    ]
    sections = _near_critical_sections(db, project)
    approved = db.scalars(
        select(MaterialRequest)
        .join(BoqItem, BoqItem.id == MaterialRequest.boq_item_id)
        .where(
            MaterialRequest.project_id == project.id, MaterialRequest.status == RequestStatus.APPROVED.value
        )
    ).all()
    return OutlookOut(
        project_id=project.id,
        expected_delivery=expected,
        lead_time_days=lead,
        suppliers=sorted(estimates, key=lambda e: (-e.chance, e.low_data, e.supplier_name)),
        critical_request_ids=[r.id for r in approved if _critical(r, sections)[0]],
        threshold=THRESHOLD,
    )
