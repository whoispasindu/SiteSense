"""Material requests: raising, checking against the rules, deciding, and the cost figures behind them.

Access always goes through the request's project (site scoping, BR-03); procurement works company-wide.
Rows that a decision depends on are locked (``FOR UPDATE``) so two people acting at once cannot both
pass a check that only one of them should pass (double approval, BR-02 quantity race).
"""

import uuid
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import Permission, Role, has_permission
from app.core.scoping import scope_to_user_sites
from app.models import (
    Approval,
    BoqItem,
    BoqSection,
    BudgetLine,
    Delivery,
    DocumentCounter,
    MaterialRequest,
    Project,
    ProjectStatus,
    PurchaseOrderLine,
    RequestStatus,
    User,
)
from app.rules import materials as rules
from app.schemas.materials import (
    Action,
    BoqItemOption,
    BoqItemRef,
    DecisionIn,
    DeliveryOut,
    HistoryEntry,
    OrderRef,
    PersonOut,
    ProjectRef,
    RequestCheck,
    RequestCreate,
    RequestDetail,
    RequestList,
    RequestSummary,
    RequestUpdate,
    RuleCheckOut,
    RuleResultOut,
)
from app.services import audit, notification_service, project_service
from app.services.audit import AuditAction, RequestMeta
from app.services.notification_service import NewNotification
from app.services.visibility import sees_rates

ZERO = Decimal(0)
OPEN_PROJECT_STATUSES = {ProjectStatus.ACTIVE.value, ProjectStatus.ON_HOLD.value}
# Requests that still count against the BOQ quantity (BR-02).
LIVE_STATUSES = tuple(
    s.value for s in RequestStatus if s not in (RequestStatus.REJECTED, RequestStatus.CANCELLED)
)
MAX_NEEDED_BY_DAYS = 2 * 366


# --- Running numbers -----------------------------------------------------------------------------


def next_number(db: Session, kind: str) -> str:
    """Gap-free document number such as MR-0007, taken under a row lock."""
    db.execute(insert(DocumentCounter).values(kind=kind, value=0).on_conflict_do_nothing())
    counter = db.scalars(select(DocumentCounter).where(DocumentCounter.kind == kind).with_for_update()).one()
    counter.value += 1
    return f"{kind}-{counter.value:04d}"


# --- Cost figures per BOQ section --------------------------------------------------------------------


@dataclass(slots=True)
class SectionCosts:
    approved: Decimal = ZERO  # approved, not yet ordered (request price)
    committed: Decimal = ZERO  # ordered, not yet delivered (order price)
    spent: Decimal = ZERO  # delivered (order price)

    @property
    def used(self) -> Decimal:
        return self.approved + self.committed + self.spent


def section_costs(db: Session, project_id: uuid.UUID) -> dict[uuid.UUID, SectionCosts]:
    """Approved, committed and spent cost per BOQ section, derived from the documents themselves."""
    costs: dict[uuid.UUID, SectionCosts] = {}

    approved = db.execute(
        select(BoqItem.section_id, func.sum(MaterialRequest.quantity * MaterialRequest.unit_price))
        .join(BoqItem, BoqItem.id == MaterialRequest.boq_item_id)
        .where(
            MaterialRequest.project_id == project_id, MaterialRequest.status == RequestStatus.APPROVED.value
        )
        .group_by(BoqItem.section_id)
    ).all()
    for section_id, amount in approved:
        costs.setdefault(section_id, SectionCosts()).approved = rules.money(Decimal(amount or 0))

    delivered = (
        select(Delivery.line_id, func.sum(Delivery.quantity).label("qty"))
        .group_by(Delivery.line_id)
        .subquery()
    )
    ordered = db.execute(
        select(
            BoqItem.section_id,
            PurchaseOrderLine.quantity,
            PurchaseOrderLine.unit_price,
            func.coalesce(delivered.c.qty, 0),
        )
        .join(MaterialRequest, MaterialRequest.id == PurchaseOrderLine.request_id)
        .join(BoqItem, BoqItem.id == MaterialRequest.boq_item_id)
        .outerjoin(delivered, delivered.c.line_id == PurchaseOrderLine.id)
        .where(MaterialRequest.project_id == project_id)
    ).all()
    for section_id, quantity, price, done in ordered:
        entry = costs.setdefault(section_id, SectionCosts())
        done = Decimal(done)
        entry.spent += rules.money(done * price)
        entry.committed += rules.money(max(quantity - done, ZERO) * price)
    return costs


# --- Facts for the rules -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ItemFacts:
    item: BoqItem
    section_amount: Decimal
    line_budget: Decimal
    line_used: Decimal
    already_requested: Decimal

    @property
    def budget_rate(self) -> Decimal:
        return rules.item_budget_rate(
            item_rate=self.item.rate, section_amount=self.section_amount, line_budget=self.line_budget
        )


def _item(db: Session, project: Project, item_id: uuid.UUID, *, lock: bool = False) -> BoqItem:
    stmt = select(BoqItem).where(BoqItem.id == item_id, BoqItem.project_id == project.id)
    item = db.scalars(stmt.with_for_update() if lock else stmt).first()
    if item is None:
        raise BusinessRuleError("Choose an item from this project's BOQ.")
    return item


def _own_cost(request: MaterialRequest) -> Decimal:
    """What this request already contributes to its section's costs (so it is not counted twice)."""
    if request.po_line is not None:
        return request.po_line.amount
    if request.status == RequestStatus.APPROVED.value:
        return rules.money(request.quantity * request.unit_price)
    return ZERO


def item_facts(
    db: Session, project: Project, item: BoqItem, *, exclude: MaterialRequest | None = None
) -> ItemFacts:
    section_amount = db.scalar(
        select(func.coalesce(func.sum(BoqItem.amount), 0)).where(BoqItem.section_id == item.section_id)
    )
    line_budget = db.scalar(select(BudgetLine.budget_amount).where(BudgetLine.section_id == item.section_id))
    requested_stmt = select(func.coalesce(func.sum(MaterialRequest.quantity), 0)).where(
        MaterialRequest.boq_item_id == item.id, MaterialRequest.status.in_(LIVE_STATUSES)
    )
    used = section_costs(db, project.id).get(item.section_id, SectionCosts()).used
    if exclude is not None:
        requested_stmt = requested_stmt.where(MaterialRequest.id != exclude.id)
        used -= _own_cost(exclude)
    return ItemFacts(
        item=item,
        section_amount=Decimal(section_amount or 0),
        line_budget=Decimal(line_budget or 0),
        line_used=used,
        already_requested=Decimal(db.scalar(requested_stmt) or 0),
    )


def evaluate(facts: ItemFacts, quantity: Decimal, unit_price: Decimal) -> RuleCheckOut:
    amount = rules.money(quantity * unit_price)
    quantity_result = rules.check_quantity(
        boq_quantity=facts.item.quantity, already_requested=facts.already_requested, requested=quantity
    )
    level, routing, fired = rules.route_approval(
        unit_price=unit_price,
        budget_rate=facts.budget_rate,
        request_amount=amount,
        line_budget=facts.line_budget,
        line_committed=facts.line_used,
    )
    results = [quantity_result, *routing]
    return RuleCheckOut(
        approval_level=level,
        blocked=any(r.blocks for r in results),
        results=[
            RuleResultOut(rule=r.rule, severity=r.severity, message=r.message, facts=r.facts) for r in results
        ],
        routed_by=fired,
        budget_rate=rules.money(facts.budget_rate),
        amount=amount,
    )


def default_price(facts: ItemFacts) -> Decimal:
    """The starting price for a request raised without one (site engineers do not see rates):
    the item's budgeted rate, or its contract rate when the section has no budget yet."""
    for candidate in (rules.money(facts.budget_rate), facts.item.rate):
        if candidate > 0:
            return candidate
    raise BusinessRuleError("This BOQ item has no rate yet. Ask the quantity surveyor to raise the request.")


def _no_prices_from(user: User, price: Decimal | None) -> None:
    """Roles that do not see rates cannot set them either: the QS prices their requests."""
    if price is not None and not sees_rates(user):
        error = BusinessRuleError(
            "Prices are set by the quantity surveyor at the QS check; leave the price out."
        )
        error.code = "price_not_allowed"
        raise error


def _blocked(check: RuleCheckOut) -> BusinessRuleError:
    blocking = next(r for r in check.results if r.severity == "block")
    error = BusinessRuleError(blocking.message, details=[{"rule": blocking.rule}])
    error.code = "rule_blocked"
    return error


# --- Reading -----------------------------------------------------------------------------------------


def _project_ref(project: Project) -> ProjectRef:
    return ProjectRef(id=project.id, code=project.code, name=project.name, site_code=project.site.code)


def _item_ref(item: BoqItem) -> BoqItemRef:
    return BoqItemRef(
        id=item.id,
        item_code=item.item_code,
        description=item.description,
        unit=item.unit,
        section_code=item.section.code,
    )


def _person(user: User) -> PersonOut:
    return PersonOut(id=user.id, full_name=user.full_name)


def to_summary(r: MaterialRequest) -> RequestSummary:
    return RequestSummary(
        id=r.id,
        number=r.number,
        project=_project_ref(r.project),
        boq_item=_item_ref(r.boq_item),
        quantity=r.quantity,
        unit_price=r.unit_price,
        amount=rules.money(r.quantity * r.unit_price),
        needed_by=r.needed_by,
        status=r.status,
        approval_level=r.approval_level,
        requested_by=_person(r.requester),
        submitted_at=r.submitted_at,
        updated_at=r.updated_at,
    )


def _scoped(stmt: Select[Any], user: User) -> Select[Any]:
    stmt = stmt.join(Project, Project.id == MaterialRequest.project_id)
    return scope_to_user_sites(stmt, Project.site_id, user)


def list_requests(
    db: Session,
    user: User,
    *,
    status: str | None,
    project_id: uuid.UUID | None,
    mine: bool,
    limit: int,
    offset: int,
) -> RequestList:
    base = _scoped(select(MaterialRequest), user)
    if project_id is not None:
        base = base.where(MaterialRequest.project_id == project_id)
    if mine:
        base = base.where(MaterialRequest.requested_by == user.id)
    counts_stmt = base.with_only_columns(MaterialRequest.status, func.count(MaterialRequest.id)).group_by(
        MaterialRequest.status
    )
    counts = {s.value: 0 for s in RequestStatus}
    counts.update({row[0]: int(row[1]) for row in db.execute(counts_stmt).all()})
    filtered = base.where(MaterialRequest.status == status) if status else base
    total = db.scalar(filtered.with_only_columns(func.count(MaterialRequest.id))) or 0
    rows = db.scalars(
        filtered.order_by(MaterialRequest.submitted_at.desc(), MaterialRequest.id).limit(limit).offset(offset)
    ).all()
    return RequestList(items=[to_summary(r) for r in rows], total=int(total), counts=counts)


def get_request(db: Session, user: User, request_id: uuid.UUID, *, lock: bool = False) -> MaterialRequest:
    stmt = select(MaterialRequest).where(MaterialRequest.id == request_id)
    request = db.scalars(stmt.with_for_update(of=MaterialRequest) if lock else stmt).first()
    if request is None:
        raise NotFoundError("Request not found.")
    try:
        project_service.get_project(db, user, request.project_id)
    except NotFoundError as exc:  # out of scope looks exactly like missing
        raise NotFoundError("Request not found.") from exc
    return request


def _can(user: User, permission: Permission) -> bool:
    return has_permission(Role(user.role), permission)


def allowed_actions(request: MaterialRequest, user: User) -> list[Action]:
    own = request.requested_by == user.id
    stage = rules.stage_for(request.status)
    actions: list[Action] = []
    if stage == "qs" and _can(user, Permission.MATERIALS_APPROVE_QS) and not own:
        actions += ["approve", "reject", "request_change"]
    if stage == "pm" and _can(user, Permission.MATERIALS_APPROVE_PM) and not own:
        actions += ["approve", "reject", "request_change"]
    if own and request.status == RequestStatus.CHANGE_REQUESTED.value:
        actions.append("edit")
    if own and request.status in ("requested", "pm_approval", "change_requested"):
        actions.append("cancel")
    if request.status == RequestStatus.APPROVED.value and _can(user, Permission.PURCHASE_ORDERS_MANAGE):
        actions.append("order")
    return actions


def to_detail(db: Session, request: MaterialRequest, user: User) -> RequestDetail:
    project = request.project
    facts = item_facts(db, project, request.boq_item, exclude=request)
    order: OrderRef | None = None
    if request.po_line is not None:
        line = request.po_line
        order = OrderRef(
            id=line.purchase_order.id,
            number=line.purchase_order.number,
            supplier_name=line.purchase_order.supplier.name,
            unit_price=line.unit_price,
            amount=line.amount,
            expected_delivery=line.purchase_order.expected_delivery,
            delivered_quantity=sum((d.quantity for d in line.deliveries), ZERO),
            deliveries=[
                DeliveryOut(
                    id=d.id,
                    quantity=d.quantity,
                    delivered_on=d.delivered_on,
                    notes=d.notes,
                    created_at=d.created_at,
                )
                for d in line.deliveries
            ],
        )
    summary = to_summary(request)
    return RequestDetail(
        **summary.model_dump(),
        notes=request.notes,
        boq_quantity=request.boq_item.quantity,
        rules=evaluate(facts, request.quantity, request.unit_price),
        history=[
            HistoryEntry(
                action=a.action,
                from_status=a.from_status,
                to_status=a.to_status,
                comment=a.comment,
                actor=_person(a.actor),
                created_at=a.created_at,
            )
            for a in request.approvals
        ],
        order=order,
        actions=allowed_actions(request, user),
    )


def boq_options(db: Session, project: Project) -> list[BoqItemOption]:
    sections = {
        s.id: (s, Decimal(amount or 0), Decimal(budget or 0))
        for s, amount, budget in db.execute(
            select(BoqSection, func.coalesce(func.sum(BoqItem.amount), 0), BudgetLine.budget_amount)
            .outerjoin(BoqItem, BoqItem.section_id == BoqSection.id)
            .join(BudgetLine, BudgetLine.section_id == BoqSection.id)
            .where(BoqSection.project_id == project.id)
            .group_by(BoqSection.id, BudgetLine.budget_amount)
        ).all()
    }
    requested = dict(
        db.execute(
            select(MaterialRequest.boq_item_id, func.sum(MaterialRequest.quantity))
            .where(MaterialRequest.project_id == project.id, MaterialRequest.status.in_(LIVE_STATUSES))
            .group_by(MaterialRequest.boq_item_id)
        ).all()
    )
    items = db.scalars(
        select(BoqItem)
        .join(BoqSection, BoqSection.id == BoqItem.section_id)
        .where(BoqItem.project_id == project.id)
        .order_by(BoqSection.position, BoqItem.position)
    ).all()
    options = []
    for item in items:
        section, section_amount, budget = sections[item.section_id]
        options.append(
            BoqItemOption(
                id=item.id,
                item_code=item.item_code,
                description=item.description,
                unit=item.unit,
                section_code=section.code,
                section_name=section.name,
                boq_quantity=item.quantity,
                requested_quantity=Decimal(requested.get(item.id) or 0),
                remaining_quantity=max(item.quantity - Decimal(requested.get(item.id) or 0), ZERO),
                budget_rate=rules.money(
                    rules.item_budget_rate(
                        item_rate=item.rate, section_amount=section_amount, line_budget=budget
                    )
                ),
            )
        )
    return options


# --- Raising and changing requests ---------------------------------------------------------------------


def _check_project_open(project: Project) -> None:
    if project.status not in OPEN_PROJECT_STATUSES:
        raise BusinessRuleError("Materials can only be requested for active or on-hold projects.")


def _check_needed_by(needed_by: date) -> None:
    today = clock.site_today()
    if needed_by < today:
        raise BusinessRuleError("The needed-by date cannot be in the past.")
    if needed_by > today + timedelta(days=MAX_NEEDED_BY_DAYS):
        raise BusinessRuleError("The needed-by date must be within two years.")


def check_request(db: Session, user: User, project: Project, data: RequestCheck) -> RuleCheckOut:
    _no_prices_from(user, data.unit_price)
    item = _item(db, project, data.boq_item_id)
    facts = item_facts(db, project, item)
    return evaluate(facts, data.quantity, data.unit_price or default_price(facts))


def _history(
    request: MaterialRequest, actor: User, action: str, frm: str | None, to: str, comment: str | None
) -> None:
    request.approvals.append(
        Approval(
            actor_id=actor.id,
            action=action,
            from_status=frm,
            to_status=to,
            comment=comment,
            created_at=clock.utcnow(),
        )
    )


def _notify_approvers(db: Session, request: MaterialRequest, project: Project) -> None:
    role = Role.QUANTITY_SURVEYOR if request.status == RequestStatus.REQUESTED.value else Role.PROJECT_MANAGER
    stage = "QS check" if role == Role.QUANTITY_SURVEYOR else "your approval"
    people = [
        p
        for p in notification_service.site_people(db, project.site_id, {role})
        if p.id != request.requested_by
    ]
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=p.id,
                kind="request_pending",
                title=f"{request.number} needs {stage}",
                body=f"{request.requester.full_name} requested {request.quantity} {request.boq_item.unit} of "
                f"{request.boq_item.description[:80]} for {project.name}.",
                link=f"/materials/{request.id}",
                project_id=project.id,
                dedupe_key=f"request-pending:{request.id}:{request.status}:{len(request.approvals)}",
            )
            for p in people
        ],
    )


def create_request(db: Session, user: User, data: RequestCreate, *, meta: RequestMeta) -> MaterialRequest:
    project = project_service.get_project(db, user, data.project_id)
    _check_project_open(project)
    _check_needed_by(data.needed_by)
    _no_prices_from(user, data.unit_price)
    # Lock the BOQ item: concurrent requests for it are checked one after another (BR-02).
    item = _item(db, project, data.boq_item_id, lock=True)
    facts = item_facts(db, project, item)
    unit_price = data.unit_price or default_price(facts)
    check = evaluate(facts, data.quantity, unit_price)
    if check.blocked:
        raise _blocked(check)

    request = MaterialRequest(
        number=next_number(db, "MR"),
        project_id=project.id,
        boq_item_id=item.id,
        requested_by=user.id,
        quantity=data.quantity,
        unit_price=unit_price,
        needed_by=data.needed_by,
        notes=data.notes,
        status=RequestStatus.REQUESTED.value,
        approval_level=check.approval_level,
        submitted_at=clock.utcnow(),
    )
    db.add(request)
    _history(request, user, "submit", None, request.status, None)
    db.flush()
    db.refresh(request)
    audit.record(
        db,
        AuditAction.REQUEST_CREATED,
        meta=meta,
        actor_id=user.id,
        target_type="material_request",
        target_id=request.id,
        details={
            "number": request.number,
            "project": project.code,
            "item": item.item_code,
            "quantity": str(data.quantity),
            "amount": str(check.amount),
            "approval_level": check.approval_level,
        },
    )
    _notify_approvers(db, request, project)
    db.commit()
    return request


def update_request(
    db: Session, user: User, request_id: uuid.UUID, data: RequestUpdate, *, meta: RequestMeta
) -> MaterialRequest:
    """The requester's changes after "change requested". Saving resubmits to the QS."""
    request = get_request(db, user, request_id, lock=True)
    if request.requested_by != user.id:
        raise ForbiddenError("Only the person who raised the request can change it.")
    if request.status != RequestStatus.CHANGE_REQUESTED.value:
        raise ConflictError("A request can only be changed after a change has been requested.")
    project = request.project
    _check_project_open(project)
    _no_prices_from(user, data.unit_price)
    changes = data.model_dump(exclude_unset=True, exclude={"comment"})
    for required in ("quantity", "unit_price", "needed_by"):
        if required in changes and changes[required] is None:
            raise BusinessRuleError(f"{required.replace('_', ' ').capitalize()} cannot be empty.")
    if "needed_by" in changes:
        _check_needed_by(changes["needed_by"])
    for name, value in changes.items():
        setattr(request, name, value)

    item = _item(db, project, request.boq_item_id, lock=True)
    check = evaluate(item_facts(db, project, item, exclude=request), request.quantity, request.unit_price)
    if check.blocked:
        db.rollback()
        raise _blocked(check)
    request.approval_level = check.approval_level
    request.submitted_at = clock.utcnow()
    _history(request, user, "resubmit", request.status, RequestStatus.REQUESTED.value, data.comment)
    request.status = RequestStatus.REQUESTED.value
    audit.record(
        db,
        AuditAction.REQUEST_UPDATED,
        meta=meta,
        actor_id=user.id,
        target_type="material_request",
        target_id=request.id,
        details={"number": request.number, "fields": sorted(changes)},
    )
    _notify_approvers(db, request, project)
    db.commit()
    db.refresh(request)
    return request


# --- Decisions ---------------------------------------------------------------------------------------------


_DECISION_TEXT = {
    "approved": "approved",
    "pm_approval": "passed the QS check; it now needs project manager approval",
    "rejected": "rejected",
    "change_requested": "returned for changes",
    "cancelled": "cancelled",
}


def decide(
    db: Session, user: User, request_id: uuid.UUID, data: DecisionIn, *, meta: RequestMeta
) -> MaterialRequest:
    request = get_request(db, user, request_id, lock=True)
    project = request.project
    own = request.requested_by == user.id

    if data.decision == "cancel":
        if not own:
            raise ForbiddenError("Only the person who raised the request can cancel it.")
        stage: rules.Stage = "requester"
    else:
        current = rules.stage_for(request.status)
        if current == "qs":
            permission = Permission.MATERIALS_APPROVE_QS
        elif current == "pm":
            permission = Permission.MATERIALS_APPROVE_PM
        else:
            raise ConflictError(
                f"No decision is pending on this request (it is {request.status.replace('_', ' ')})."
            )
        if not _can(user, permission):  # TC-01: e.g. a site engineer trying to approve
            who = "quantity surveyor" if current == "qs" else "project manager"
            raise ForbiddenError(f"This request is waiting for the {who}.")
        segregation = rules.check_not_own_request(actor_id=user.id, requester_id=request.requested_by)
        if segregation.blocks:  # BR-04, TC-05
            error = ForbiddenError(segregation.message)
            error.code = "own_request"
            raise error
        stage = current
        if data.decision in ("reject", "request_change") and not data.comment:
            raise BusinessRuleError("Add a comment so the requester knows why.")

    if data.unit_price is not None:
        if not (stage == "qs" and data.decision == "approve"):
            raise BusinessRuleError(
                "A price can only be set by the quantity surveyor when approving at the QS check."
            )
        request.unit_price = data.unit_price
    level = request.approval_level
    if stage == "qs" and data.decision == "approve":
        # Re-check routing with today's figures (and the QS's price): commitments may have changed.
        facts = item_facts(db, project, request.boq_item, exclude=request)
        level = evaluate(facts, request.quantity, request.unit_price).approval_level
        request.approval_level = level
    try:
        target = rules.next_status(
            status=request.status,
            decision=data.decision,
            stage=stage,
            approval_level=level,  # type: ignore[arg-type]
        )
    except rules.TransitionError as exc:
        conflict = ConflictError(str(exc))
        conflict.code = "invalid_transition"
        raise conflict from exc

    previous = request.status
    _history(request, user, data.decision, previous, target, data.comment)
    request.status = target
    audit.record(
        db,
        AuditAction.REQUEST_DECIDED,
        meta=meta,
        actor_id=user.id,
        target_type="material_request",
        target_id=request.id,
        details={
            "number": request.number,
            "decision": data.decision,
            "from": previous,
            "to": target,
            **({"unit_price": str(data.unit_price)} if data.unit_price is not None else {}),
        },
    )

    notes: list[NewNotification] = []
    if not own:
        notes.append(
            NewNotification(
                user_id=request.requested_by,
                kind=f"request_{target}",
                title=f"{request.number} {_DECISION_TEXT.get(target, target)}",
                body=f"{user.full_name}: {data.comment}"
                if data.comment
                else f"Decision by {user.full_name}.",
                link=f"/materials/{request.id}",
                project_id=project.id,
                dedupe_key=f"request-decision:{request.id}:{len(request.approvals)}",
            )
        )
    if target == RequestStatus.APPROVED.value:
        notes += [
            NewNotification(
                user_id=p.id,
                kind="request_ready_to_order",
                title=f"{request.number} is ready to order",
                body=f"{request.quantity} {request.boq_item.unit} of {request.boq_item.description[:80]} "
                f"for {project.name}, needed by {request.needed_by.strftime('%d %b %Y')}.",
                link=f"/materials/{request.id}",
                project_id=project.id,
                dedupe_key=f"request-ready:{request.id}",
            )
            for p in notification_service.company_people(db, {Role.PROCUREMENT_OFFICER})
        ]
    notification_service.send(db, notes)
    if target == RequestStatus.PM_APPROVAL.value:
        _notify_approvers(db, request, project)
    db.commit()
    db.refresh(request)
    return request
