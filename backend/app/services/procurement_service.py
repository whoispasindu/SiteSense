"""Suppliers, purchase orders and deliveries (procurement), and the project budget they feed.

BR-05: only approved requests can go on a purchase order. The order price may not exceed the approved
request price, so the approval route chosen under BR-01 cannot be side-stepped at the ordering stage.
Committed and spent cost are derived from order lines and deliveries (``section_costs``).
"""

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import Role
from app.core.scoping import scope_to_user_sites
from app.models import (
    Approval,
    BoqItem,
    BoqSection,
    BudgetLine,
    Delivery,
    MaterialRequest,
    Project,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    RequestStatus,
    Supplier,
    User,
)
from app.rules import materials as rules
from app.schemas.materials import (
    BudgetFigures,
    BudgetLineOut,
    BudgetOut,
    DeliveryIn,
    DeliveryOut,
    OrderLineOut,
    PersonOut,
    ProjectRef,
    PurchaseOrderCreate,
    PurchaseOrderDetail,
    PurchaseOrderSummary,
    SupplierIn,
    SupplierOut,
    SupplierUpdate,
)
from app.services import audit, notification_service
from app.services.audit import AuditAction, RequestMeta
from app.services.materials_service import SectionCosts, next_number, section_costs
from app.services.notification_service import NewNotification

ZERO = Decimal(0)
MAX_EXPECTED_DAYS = 366


# --- Suppliers ---------------------------------------------------------------------------------------


def list_suppliers(db: Session, *, include_inactive: bool) -> list[Supplier]:
    stmt = select(Supplier).order_by(Supplier.name)
    if not include_inactive:
        stmt = stmt.where(Supplier.is_active.is_(True))
    return list(db.scalars(stmt).all())


def _save_supplier(db: Session, supplier: Supplier) -> None:
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A supplier with this name already exists.") from exc


def create_supplier(db: Session, user: User, data: SupplierIn, *, meta: RequestMeta) -> Supplier:
    supplier = Supplier(**data.model_dump())
    db.add(supplier)
    _save_supplier(db, supplier)
    audit.record(
        db,
        AuditAction.SUPPLIER_CREATED,
        meta=meta,
        actor_id=user.id,
        target_type="supplier",
        target_id=supplier.id,
        details={"name": supplier.name},
    )
    db.commit()
    return supplier


def update_supplier(
    db: Session, user: User, supplier_id: uuid.UUID, data: SupplierUpdate, *, meta: RequestMeta
) -> Supplier:
    supplier = db.get(Supplier, supplier_id)
    if supplier is None:
        raise NotFoundError("Supplier not found.")
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise BusinessRuleError("Name cannot be empty.")
    for name, value in changes.items():
        setattr(supplier, name, value)
    _save_supplier(db, supplier)
    audit.record(
        db,
        AuditAction.SUPPLIER_UPDATED,
        meta=meta,
        actor_id=user.id,
        target_type="supplier",
        target_id=supplier.id,
        details={"fields": sorted(changes)},
    )
    db.commit()
    return supplier


# --- Purchase orders -----------------------------------------------------------------------------------


def _delivered(line: PurchaseOrderLine) -> Decimal:
    return sum((d.quantity for d in line.deliveries), ZERO)


def _project_ref(project: Project) -> ProjectRef:
    return ProjectRef(id=project.id, code=project.code, name=project.name, site_code=project.site.code)


def to_po_summary(po: PurchaseOrder) -> PurchaseOrderSummary:
    return PurchaseOrderSummary(
        id=po.id,
        number=po.number,
        project=_project_ref(po.project),
        supplier=SupplierOut.model_validate(po.supplier),
        status=po.status,
        total=sum((line.amount for line in po.lines), ZERO),
        issued_at=po.issued_at,
        expected_delivery=po.expected_delivery,
        issued_by=PersonOut(id=po.issuer.id, full_name=po.issuer.full_name),
    )


def to_po_detail(po: PurchaseOrder) -> PurchaseOrderDetail:
    return PurchaseOrderDetail(
        **to_po_summary(po).model_dump(),
        notes=po.notes,
        lines=[
            OrderLineOut(
                id=line.id,
                request_id=line.request_id,
                request_number=line.request.number,
                item_code=line.request.boq_item.item_code,
                description=line.request.boq_item.description,
                unit=line.request.boq_item.unit,
                quantity=line.quantity,
                unit_price=line.unit_price,
                amount=line.amount,
                delivered_quantity=_delivered(line),
            )
            for line in po.lines
        ],
        deliveries=sorted(
            (
                DeliveryOut(
                    id=d.id,
                    quantity=d.quantity,
                    delivered_on=d.delivered_on,
                    notes=d.notes,
                    created_at=d.created_at,
                    request_number=line.request.number,
                    unit=line.request.boq_item.unit,
                )
                for line in po.lines
                for d in line.deliveries
            ),
            key=lambda d: (d.delivered_on, d.created_at),
        ),
    )


def list_orders(
    db: Session, user: User, *, status: str | None, limit: int, offset: int
) -> tuple[list[PurchaseOrder], int]:
    stmt = scope_to_user_sites(
        select(PurchaseOrder).join(Project, Project.id == PurchaseOrder.project_id), Project.site_id, user
    )
    if status:
        stmt = stmt.where(PurchaseOrder.status == status)
    total = db.scalar(stmt.with_only_columns(func.count(PurchaseOrder.id))) or 0
    rows = db.scalars(
        stmt.order_by(PurchaseOrder.issued_at.desc(), PurchaseOrder.id).limit(limit).offset(offset)
    ).all()
    return list(rows), int(total)


def get_order(db: Session, user: User, order_id: uuid.UUID, *, lock: bool = False) -> PurchaseOrder:
    stmt = select(PurchaseOrder).where(PurchaseOrder.id == order_id)
    po = db.scalars(stmt.with_for_update(of=PurchaseOrder) if lock else stmt).first()
    if po is None:
        raise NotFoundError("Purchase order not found.")
    allowed = scope_to_user_sites(
        select(Project.id).where(Project.id == po.project_id), Project.site_id, user
    )
    if db.scalar(allowed) is None:
        raise NotFoundError("Purchase order not found.")
    return po


def ready_to_order(db: Session) -> list[MaterialRequest]:
    """Approved requests not yet on a purchase order, oldest need first (procurement works company-wide)."""
    return list(
        db.scalars(
            select(MaterialRequest)
            .where(MaterialRequest.status == RequestStatus.APPROVED.value)
            .order_by(MaterialRequest.needed_by, MaterialRequest.number)
        ).all()
    )


def create_order(db: Session, user: User, data: PurchaseOrderCreate, *, meta: RequestMeta) -> PurchaseOrder:
    supplier = db.get(Supplier, data.supplier_id)
    if supplier is None or not supplier.is_active:
        raise BusinessRuleError("Choose an active supplier.")
    today = clock.site_today()
    if data.expected_delivery < today or data.expected_delivery > today + timedelta(days=MAX_EXPECTED_DAYS):
        raise BusinessRuleError("The expected delivery date must be between today and a year from now.")

    ids = [line.request_id for line in data.lines]
    # Lock the requests so the same request cannot be ordered twice by two people at once.
    requests = {
        r.id: r
        for r in db.scalars(
            select(MaterialRequest).where(MaterialRequest.id.in_(ids)).with_for_update(of=MaterialRequest)
        ).all()
    }
    if len(requests) != len(ids):
        raise BusinessRuleError("One of the requests no longer exists.")
    projects = {r.project_id for r in requests.values()}
    if len(projects) != 1:
        raise BusinessRuleError("A purchase order covers one project; order other projects separately.")
    for request in requests.values():
        gate = rules.check_can_order(status=request.status)  # BR-05
        if gate.blocks:
            error = BusinessRuleError(f"{request.number}: {gate.message}", details=[{"rule": "BR-05"}])
            error.code = "rule_blocked"
            raise error

    po = PurchaseOrder(
        number=next_number(db, "PO"),
        project_id=projects.pop(),
        supplier_id=supplier.id,
        issued_by=user.id,
        issued_at=clock.utcnow(),
        expected_delivery=data.expected_delivery,
        status=PurchaseOrderStatus.ISSUED.value,
        notes=data.notes,
    )
    db.add(po)
    for position, line_in in enumerate(data.lines, start=1):
        request = requests[line_in.request_id]
        price = line_in.unit_price or request.unit_price
        if price > request.unit_price:
            raise BusinessRuleError(
                f"{request.number}: the order price {price} is above the approved price "
                f"{request.unit_price}. Ask for the request to be changed and approved again."
            )
        po.lines.append(
            PurchaseOrderLine(
                request_id=request.id,
                quantity=request.quantity,
                unit_price=price,
                amount=rules.money(request.quantity * price),
                position=position,
            )
        )
        request.approvals.append(
            Approval(
                actor_id=user.id,
                action="order",
                from_status=request.status,
                to_status=RequestStatus.ORDERED.value,
                comment=None,
                created_at=clock.utcnow(),
            )
        )
        request.status = RequestStatus.ORDERED.value
    try:
        db.flush()
    except IntegrityError as exc:  # unique request_id on order lines: already ordered elsewhere
        db.rollback()
        raise ConflictError("One of the requests is already on a purchase order.") from exc

    audit.record(
        db,
        AuditAction.PURCHASE_ORDER_ISSUED,
        meta=meta,
        actor_id=user.id,
        target_type="purchase_order",
        target_id=po.id,
        details={
            "number": po.number,
            "supplier": supplier.name,
            "requests": [requests[i].number for i in ids],
            "total": str(sum((line.amount for line in po.lines), ZERO)),
        },
    )
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=r.requested_by,
                kind="request_ordered",
                title=f"{r.number} ordered on {po.number}",
                body=f"From {supplier.name}, expected {data.expected_delivery.strftime('%d %b %Y')}.",
                link=f"/materials/{r.id}",
                project_id=r.project_id,
                dedupe_key=f"request-ordered:{r.id}",
            )
            for r in requests.values()
        ],
    )
    db.commit()
    db.refresh(po)
    return po


def record_delivery(
    db: Session, user: User, order_id: uuid.UUID, data: DeliveryIn, *, meta: RequestMeta
) -> PurchaseOrder:
    po = get_order(db, user, order_id, lock=True)
    line = next((line for line in po.lines if line.request_id == data.request_id), None)
    if line is None:
        raise BusinessRuleError("That request is not on this purchase order.")
    if data.delivered_on > clock.site_today():
        raise BusinessRuleError("A delivery cannot be dated in the future.")
    if data.delivered_on < po.issued_at.astimezone(clock.SITE_TIME_ZONE).date():
        raise BusinessRuleError("A delivery cannot be dated before the order was issued.")
    remaining = line.quantity - _delivered(line)
    if data.quantity > remaining:
        raise BusinessRuleError(
            f"Only {remaining} {line.request.boq_item.unit} remain to be delivered on this line."
        )

    line.deliveries.append(
        Delivery(
            quantity=data.quantity,
            delivered_on=data.delivered_on,
            received_by=user.id,
            notes=data.notes,
            created_at=clock.utcnow(),
        )
    )
    request = line.request
    complete = _delivered(line) >= line.quantity
    if complete:
        request.approvals.append(
            Approval(
                actor_id=user.id,
                action="deliver",
                from_status=request.status,
                to_status=RequestStatus.DELIVERED.value,
                comment=None,
                created_at=clock.utcnow(),
            )
        )
        request.status = RequestStatus.DELIVERED.value
    all_done = all(_delivered(item) >= item.quantity for item in po.lines)
    po.status = (PurchaseOrderStatus.DELIVERED if all_done else PurchaseOrderStatus.PART_DELIVERED).value

    audit.record(
        db,
        AuditAction.DELIVERY_RECORDED,
        meta=meta,
        actor_id=user.id,
        target_type="purchase_order",
        target_id=po.id,
        details={"number": po.number, "request": request.number, "quantity": str(data.quantity)},
    )
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=request.requested_by,
                kind="request_delivered" if complete else "request_part_delivered",
                title=f"{request.number} {'delivered' if complete else 'partly delivered'}",
                body=f"{data.quantity} {line.request.boq_item.unit} received on "
                f"{data.delivered_on.strftime('%d %b %Y')}.",
                link=f"/materials/{request.id}",
                project_id=request.project_id,
                dedupe_key=f"delivery:{line.id}:{len(line.deliveries)}",
            )
        ],
    )
    db.commit()
    db.refresh(po)
    return po


# --- Budget ---------------------------------------------------------------------------------------------


def project_budget(db: Session, project: Project) -> BudgetOut:
    costs = section_costs(db, project.id)
    rows = db.execute(
        select(BoqSection, func.coalesce(func.sum(BoqItem.amount), 0), BudgetLine.budget_amount)
        .join(BudgetLine, BudgetLine.section_id == BoqSection.id)
        .outerjoin(BoqItem, BoqItem.section_id == BoqSection.id)
        .where(BoqSection.project_id == project.id)
        .group_by(BoqSection.id, BudgetLine.budget_amount)
        .order_by(BoqSection.position)
    ).all()

    def figures(boq: Decimal, budget: Decimal, c: SectionCosts) -> dict[str, Decimal]:
        forecast = c.spent + c.committed + c.approved
        return {
            "boq_amount": rules.money(boq),
            "budget": rules.money(budget),
            "approved": rules.money(c.approved),
            "committed": rules.money(c.committed),
            "spent": rules.money(c.spent),
            "remaining": rules.money(budget - c.committed - c.spent),
            "forecast": rules.money(forecast),
            "variance": rules.money(budget - forecast),
        }

    lines = []
    total = SectionCosts()
    total_boq = total_budget = ZERO
    for section, boq, budget in rows:
        c = costs.get(section.id, SectionCosts())
        total.approved += c.approved
        total.committed += c.committed
        total.spent += c.spent
        total_boq += Decimal(boq)
        total_budget += budget
        lines.append(
            BudgetLineOut(
                section_id=section.id,
                code=section.code,
                name=section.name,
                **figures(Decimal(boq), budget, c),
            )
        )
    return BudgetOut(
        project_id=project.id, lines=lines, totals=BudgetFigures(**figures(total_boq, total_budget, total))
    )


def procurement_people(db: Session) -> list[User]:
    return notification_service.company_people(db, {Role.PROCUREMENT_OFFICER})
