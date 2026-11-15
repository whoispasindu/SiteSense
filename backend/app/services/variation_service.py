"""Variation orders (Phase 8, BR-09).

Workflow D in the build guide, with the project owner's decisions:

    1. A PM or QS raises a variation: what changes, which BOQ section, optionally extra quantity on
       one BOQ item (it raises that item's BR-02 allowance) and the task its time impact delays.
    2. The QS prices every variation: the change to the contract value (what the client pays) and to
       the section's cost budget. A QS can price it while raising it.
    3. Routing (``app.rules.variations``): any time impact, or a contract change above the project's
       limit, goes to the client; otherwise a QS's variation goes to a PM, and a PM's to the client.
    4. The PM approves, queries or rejects; the client approves or queries. A query sends it back to
       the raiser and the QS to revise (it is priced again) or withdraw.
    5. On approval the contract value, the section's budget line, the task and the project's planned
       end change, in one transaction, audited with before and after values (TC-10). The project's
       risk is re-scored and its cost variance checked.

Every step is a ``variation_events`` row. The client sees a variation once it has been sent to them,
in a separate view without internal costs or internal comments.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock, company
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import Permission, Role, has_permission
from app.models import BoqItem, BoqSection, BudgetLine, Project, Task, User, VariationEvent, VariationOrder
from app.rules import variations as rules
from app.rules.materials import ZERO, money
from app.rules.variations import VariationStatus
from app.schemas.contract import (
    ClientDecisionIn,
    ClientVariationOut,
    ProjectLimitIn,
    ProjectLimitOut,
    VariationAction,
    VariationDecisionIn,
    VariationEventOut,
    VariationIn,
    VariationListOut,
    VariationOut,
    VariationPriceIn,
    WithdrawIn,
)
from app.services import (
    audit,
    client_access,
    cost_service,
    notification_service,
    project_service,
    risk_service,
)
from app.services.audit import AuditAction, RequestMeta
from app.services.materials_service import next_number
from app.services.notification_service import NewNotification

S = VariationStatus
_PAST = {"approve": "approved", "query": "queried", "reject": "rejected"}


def _can(user: User, permission: Permission) -> bool:
    return has_permission(Role(user.role), permission)


def _role_code(user: User) -> rules.RaisedBy:
    return "pm" if user.role == Role.PROJECT_MANAGER.value else "qs"


# --- Loading --------------------------------------------------------------------------------------------


def get_variation(db: Session, user: User, variation_id: uuid.UUID, *, lock: bool = False) -> VariationOrder:
    stmt = select(VariationOrder).where(VariationOrder.id == variation_id)
    variation = db.scalars(stmt.with_for_update(of=VariationOrder) if lock else stmt).first()
    if variation is None:
        raise NotFoundError("Variation not found.")
    try:
        project_service.get_project(db, user, variation.project_id)
    except NotFoundError as exc:
        raise NotFoundError("Variation not found.") from exc
    return variation


def _client_variation(
    db: Session, user: User, variation_id: uuid.UUID, *, lock: bool = False
) -> VariationOrder:
    """For the client: on a project they are linked to, once sent to them; else the same 404 as missing."""
    stmt = select(VariationOrder).where(VariationOrder.id == variation_id)
    variation = db.scalars(stmt.with_for_update(of=VariationOrder) if lock else stmt).first()
    if (
        variation is None
        or variation.sent_to_client_at is None
        or not client_access.can_see(user, variation.project_id)
    ):
        raise NotFoundError("Variation not found.")
    return variation


def _project(db: Session, variation: VariationOrder) -> Project:
    project = db.get(Project, variation.project_id)
    assert project is not None  # a foreign key
    return project


# --- Output ---------------------------------------------------------------------------------------------


def _names(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.full_name).where(User.id.in_(ids))).all())


def _event_out(event: VariationEvent, *, for_client: bool = False) -> VariationEventOut:
    by_client = event.actor.role == Role.CLIENT.value
    return VariationEventOut(
        action=event.action,
        actor=event.actor.full_name if (by_client or not for_client) else "Contractor",
        from_status=event.from_status,
        to_status=event.to_status,
        # The client sees only their own comments: internal notes (pricing, PM queries) stay internal.
        comment=event.comment if (by_client or not for_client) else None,
        at=event.created_at,
    )


def actions_for(variation: VariationOrder, user: User) -> list[VariationAction]:
    actions: list[VariationAction] = []
    own = variation.raised_by == user.id
    if variation.status == S.AWAITING_PRICING and _can(user, Permission.VARIATIONS_PRICE):
        actions.append("price")
    if variation.status == S.QUERIED and (own or _can(user, Permission.VARIATIONS_PRICE)):
        actions.append("revise")
    if variation.status == S.AWAITING_PM and _can(user, Permission.VARIATIONS_APPROVE) and not own:
        actions += ["approve", "query", "reject"]
    if variation.status in rules.OPEN_STATUSES and own:
        actions.append("withdraw")
    return actions


def variation_out(db: Session, variation: VariationOrder, user: User) -> VariationOut:
    project = _project(db, variation)
    item = db.get(BoqItem, variation.boq_item_id) if variation.boq_item_id else None
    task = db.get(Task, variation.task_id) if variation.task_id else None
    priced_by = _names(db, {variation.priced_by} if variation.priced_by else set())
    priced = variation.contract_change is not None
    return VariationOut(
        id=variation.id,
        number=variation.number,
        project_id=project.id,
        project_code=project.code,
        title=variation.title,
        description=variation.description,
        section_id=variation.section_id,
        section=f"{variation.section.code} {variation.section.name}",
        boq_item_id=variation.boq_item_id,
        boq_item=f"{item.item_code} {item.description[:120]}" if item else None,
        quantity_change=variation.quantity_change,
        task_id=variation.task_id,
        task=task.name if task else None,
        time_impact_days=variation.time_impact_days,
        contract_change=variation.contract_change,
        budget_change=variation.budget_change,
        status=variation.status,
        approver=variation.approver,
        limit=project.variation_limit,
        limit_applied=variation.limit_applied,
        needs_client=rules.needs_client(
            contract_change=variation.contract_change or ZERO,
            time_impact_days=variation.time_impact_days,
            limit=variation.limit_applied if variation.limit_applied is not None else project.variation_limit,
        )
        if priced
        else None,
        raised_by=variation.raiser.full_name,
        raised_by_role=variation.raised_by_role,
        raised_at=variation.raised_at,
        priced_by=priced_by.get(variation.priced_by) if variation.priced_by else None,
        decided_at=variation.decided_at,
        events=[_event_out(e) for e in variation.events],
        actions=actions_for(variation, user),
    )


def list_variations(db: Session, user: User, project_id: uuid.UUID) -> VariationListOut:
    project = project_service.get_project(db, user, project_id)
    rows = db.scalars(
        select(VariationOrder)
        .where(VariationOrder.project_id == project.id)
        .order_by(VariationOrder.raised_at.desc())
    ).all()
    approved = [v for v in rows if v.status == S.APPROVED]
    return VariationListOut(
        variations=[variation_out(db, v, user) for v in rows],
        limit=project.variation_limit,
        approved_contract_change=money(sum((v.contract_change or ZERO for v in approved), ZERO)),
        approved_time_impact_days=sum(v.time_impact_days for v in approved),
    )


def _reason_for_client(variation: VariationOrder) -> str:
    limit = variation.limit_applied or ZERO
    if variation.time_impact_days > 0:
        return f"It changes the completion date by {variation.time_impact_days} days."
    if variation.contract_change is not None and abs(variation.contract_change) > limit:
        return f"It changes the contract by more than the agreed limit of {company.money(limit)}."
    if variation.raised_by_role == "pm":
        return "It was raised by the project manager, so it is approved by you rather than by them."
    return "It was sent to you for approval."


def client_out(db: Session, variation: VariationOrder, user: User) -> ClientVariationOut:
    project = _project(db, variation)
    shown = [e for e in variation.events if e.client_visible]
    return ClientVariationOut(
        id=variation.id,
        number=variation.number,
        project_id=project.id,
        project_code=project.code,
        project_name=project.name,
        title=variation.title,
        description=variation.description,
        contract_change=variation.contract_change,
        time_impact_days=variation.time_impact_days,
        status=variation.status,
        limit=project.variation_limit,
        reason_for_client=_reason_for_client(variation),
        raised_at=variation.raised_at,
        events=[_event_out(e, for_client=True) for e in shown],
        can_decide=variation.status == S.AWAITING_CLIENT and _can(user, Permission.VARIATIONS_CLIENT_DECIDE),
    )


def client_list(db: Session, user: User) -> list[ClientVariationOut]:
    stmt = (
        select(VariationOrder)
        .join(Project, Project.id == VariationOrder.project_id)
        .where(VariationOrder.sent_to_client_at.is_not(None))
        .order_by(VariationOrder.sent_to_client_at.desc())
    )
    rows = db.scalars(stmt.where(VariationOrder.project_id.in_(client_access.project_ids(user)))).all()
    return [client_out(db, v, user) for v in rows]


def client_get(db: Session, user: User, variation_id: uuid.UUID) -> ClientVariationOut:
    return client_out(db, _client_variation(db, user, variation_id), user)


# --- Steps ----------------------------------------------------------------------------------------------


def _event(
    variation: VariationOrder,
    actor: User,
    action: str,
    before: str | None,
    comment: str | None = None,
    *,
    client_visible: bool = False,
) -> None:
    variation.events.append(
        VariationEvent(
            actor_id=actor.id,
            action=action,
            from_status=before,
            to_status=variation.status,
            comment=comment,
            client_visible=client_visible,
            created_at=clock.utcnow(),
        )
    )


def _validated_scope(db: Session, project: Project, data: VariationIn) -> None:
    section = db.get(BoqSection, data.section_id)
    if section is None or section.project_id != project.id:
        raise BusinessRuleError("Choose a section of this project's BOQ.")
    if (data.boq_item_id is None) != (data.quantity_change is None):
        raise BusinessRuleError("Extra quantity needs its BOQ item, and an item needs the extra quantity.")
    if data.boq_item_id is not None:
        item = db.get(BoqItem, data.boq_item_id)
        if item is None or item.section_id != section.id:
            raise BusinessRuleError("The BOQ item must be in the chosen section.")
    if data.task_id is not None:
        task = db.get(Task, data.task_id)
        if task is None or task.project_id != project.id:
            raise BusinessRuleError("Choose a task from this project's programme.")
    if data.time_impact_days > 0 and data.task_id is None:
        raise BusinessRuleError("A time impact needs the programme task it delays.")


def _check_price(
    db: Session, project: Project, section_id: uuid.UUID, contract: Decimal, budget: Decimal
) -> None:
    if project.contract_value + contract <= ZERO:
        raise BusinessRuleError("This would take the contract value to zero or below.")
    line = db.scalar(select(BudgetLine.budget_amount).where(BudgetLine.section_id == section_id))
    problem = rules.check_budget_change(line_budget=Decimal(line or 0), budget_change=budget)
    if problem:
        raise BusinessRuleError(problem)


def _route(
    db: Session, variation: VariationOrder, project: Project, actor: User, comment: str | None
) -> None:
    """Set the price's routing (BR-09), record the step, and tell whoever decides next."""
    approver = rules.route(
        contract_change=variation.contract_change or ZERO,
        time_impact_days=variation.time_impact_days,
        limit=project.variation_limit,
        raised_by=variation.raised_by_role,  # type: ignore[arg-type]
        seen_by_client=variation.sent_to_client_at is not None,
    )
    before = variation.status
    variation.approver = approver
    variation.limit_applied = project.variation_limit
    variation.status = rules.status_for(approver)
    to_client = approver == "client"
    if to_client and variation.sent_to_client_at is None:
        variation.sent_to_client_at = clock.utcnow()
    _event(variation, actor, "priced", before, comment, client_visible=to_client)
    # Clients are told only about their own projects (Phase 12), never through the site.
    candidates = (
        client_access.clients_of(db, project.id)
        if to_client
        else notification_service.site_people(db, project.site_id, {Role.PROJECT_MANAGER})
    )
    people = [p for p in candidates if p.id != variation.raised_by]
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=p.id,
                kind="variation_for_client" if to_client else "variation_for_pm",
                title=f"{variation.number} needs your decision",
                body=f"{project.code}: {variation.title}",
                link=f"/client/variations/{variation.id}" if to_client else f"/variations/{variation.id}",
                project_id=project.id,
                dedupe_key=f"variation-routed:{variation.id}:{len(variation.events)}",
            )
            for p in people
        ],
    )


def _notify_pricers(db: Session, variation: VariationOrder, project: Project) -> None:
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=qs.id,
                kind="variation_to_price",
                title=f"{variation.number} to price",
                body=f"{project.code}: {variation.title}",
                link=f"/variations/{variation.id}",
                project_id=project.id,
                dedupe_key=f"variation-to-price:{variation.id}:{len(variation.events)}",
            )
            for qs in notification_service.site_people(db, project.site_id, {Role.QUANTITY_SURVEYOR})
            if qs.id != variation.raised_by
        ],
    )


def raise_variation(
    db: Session, user: User, project_id: uuid.UUID, data: VariationIn, *, meta: RequestMeta
) -> VariationOrder:
    project = project_service.get_project(db, user, project_id)
    _validated_scope(db, project, data)
    priced = _price_in(user, data)
    variation = VariationOrder(
        number=next_number(db, "VO"),
        project_id=project.id,
        title=data.title,
        description=data.description,
        section_id=data.section_id,
        boq_item_id=data.boq_item_id,
        quantity_change=data.quantity_change,
        task_id=data.task_id,
        time_impact_days=data.time_impact_days,
        status=S.AWAITING_PRICING.value,
        raised_by=user.id,
        raised_by_role=_role_code(user),
        raised_at=clock.utcnow(),
    )
    db.add(variation)
    _event(variation, user, "raised", None, data.comment)
    if priced is not None:
        _set_price(db, variation, project, user, *priced)
        _route(db, variation, project, user, None)
    else:
        _notify_pricers(db, variation, project)
    db.flush()
    audit.record(
        db,
        AuditAction.VARIATION_RAISED,
        meta=meta,
        actor_id=user.id,
        target_type="variation_order",
        target_id=variation.id,
        details={"number": variation.number, "project": project.code, "status": variation.status},
    )
    db.commit()
    db.refresh(variation)
    return variation


def _price_in(user: User, data: VariationIn) -> tuple[Decimal, Decimal] | None:
    if data.contract_change is None and data.budget_change is None:
        return None
    if not _can(user, Permission.VARIATIONS_PRICE):
        raise ForbiddenError("Only the quantity surveyor prices variations.")
    if data.contract_change is None or data.budget_change is None:
        raise BusinessRuleError("Price both the contract change and the budget change.")
    return data.contract_change, data.budget_change


def _set_price(
    db: Session, variation: VariationOrder, project: Project, user: User, contract: Decimal, budget: Decimal
) -> None:
    _check_price(db, project, variation.section_id, contract, budget)
    variation.contract_change = contract
    variation.budget_change = budget
    variation.priced_by = user.id
    variation.priced_at = clock.utcnow()


def price(
    db: Session, user: User, variation_id: uuid.UUID, data: VariationPriceIn, *, meta: RequestMeta
) -> VariationOrder:
    variation = get_variation(db, user, variation_id, lock=True)
    if not _can(user, Permission.VARIATIONS_PRICE):
        raise ForbiddenError("Only the quantity surveyor prices variations.")
    if variation.status != S.AWAITING_PRICING:
        raise ConflictError("This variation is not waiting to be priced.")
    project = _locked_project(db, variation)
    _set_price(db, variation, project, user, data.contract_change, data.budget_change)
    _route(db, variation, project, user, data.comment)
    audit.record(
        db,
        AuditAction.VARIATION_PRICED,
        meta=meta,
        actor_id=user.id,
        target_type="variation_order",
        target_id=variation.id,
        details={
            "number": variation.number,
            "contract_change": str(data.contract_change),
            "budget_change": str(data.budget_change),
            "limit": str(variation.limit_applied),
            "routed_to": variation.approver,
        },
    )
    db.commit()
    db.refresh(variation)
    return variation


def revise(
    db: Session, user: User, variation_id: uuid.UUID, data: VariationIn, *, meta: RequestMeta
) -> VariationOrder:
    """A queried variation, changed by its raiser or a QS. It is priced again before it goes anywhere."""
    variation = get_variation(db, user, variation_id, lock=True)
    if variation.status != S.QUERIED:
        raise ConflictError("Only a queried variation can be revised.")
    if variation.raised_by != user.id and not _can(user, Permission.VARIATIONS_PRICE):
        raise ForbiddenError("The person who raised it, or a quantity surveyor, revises a variation.")
    project = _locked_project(db, variation)
    _validated_scope(db, project, data)
    priced = _price_in(user, data)
    before = variation.status
    for field in ("title", "description", "section_id", "boq_item_id", "quantity_change", "task_id"):
        setattr(variation, field, getattr(data, field))
    variation.time_impact_days = data.time_impact_days
    variation.contract_change = variation.budget_change = None
    variation.priced_by = variation.priced_at = None
    variation.approver = variation.limit_applied = None
    variation.status = S.AWAITING_PRICING.value
    _event(
        variation,
        user,
        "revised",
        before,
        data.comment,
        client_visible=variation.sent_to_client_at is not None,
    )
    if priced is not None:
        _set_price(db, variation, project, user, *priced)
        _route(db, variation, project, user, None)
    else:
        _notify_pricers(db, variation, project)
    audit.record(
        db,
        AuditAction.VARIATION_REVISED,
        meta=meta,
        actor_id=user.id,
        target_type="variation_order",
        target_id=variation.id,
        details={"number": variation.number, "status": variation.status},
    )
    db.commit()
    db.refresh(variation)
    return variation


def withdraw(
    db: Session, user: User, variation_id: uuid.UUID, data: WithdrawIn, *, meta: RequestMeta
) -> VariationOrder:
    variation = get_variation(db, user, variation_id, lock=True)
    if variation.raised_by != user.id:
        raise ForbiddenError("Only the person who raised a variation can withdraw it.")
    if variation.status not in rules.OPEN_STATUSES:
        raise ConflictError("This variation is already closed.")
    before = variation.status
    variation.status = S.WITHDRAWN.value
    _event(
        variation,
        user,
        "withdrawn",
        before,
        data.comment,
        client_visible=variation.sent_to_client_at is not None,
    )
    audit.record(
        db,
        AuditAction.VARIATION_WITHDRAWN,
        meta=meta,
        actor_id=user.id,
        target_type="variation_order",
        target_id=variation.id,
        details={"number": variation.number, "from": before},
    )
    db.commit()
    db.refresh(variation)
    return variation


def decide(
    db: Session, user: User, variation_id: uuid.UUID, data: VariationDecisionIn, *, meta: RequestMeta
) -> VariationOrder:
    """The PM's decision on a variation routed to the PM."""
    variation = get_variation(db, user, variation_id, lock=True)
    if not _can(user, Permission.VARIATIONS_APPROVE):
        raise ForbiddenError("Only a project manager decides on variations.")
    if variation.raised_by == user.id:
        raise ForbiddenError("You raised this variation, so someone else must approve it.")
    return _decide(db, user, variation, data.decision, data.comment, by="pm", meta=meta)


def client_decide(
    db: Session, user: User, variation_id: uuid.UUID, data: ClientDecisionIn, *, meta: RequestMeta
) -> ClientVariationOut:
    variation = _client_variation(db, user, variation_id, lock=True)
    _decide(db, user, variation, data.decision, data.comment, by="client", meta=meta)
    return client_out(db, variation, user)


def _decide(
    db: Session,
    user: User,
    variation: VariationOrder,
    decision: rules.Decision,
    comment: str | None,
    *,
    by: rules.Approver,
    meta: RequestMeta,
) -> VariationOrder:
    if decision in ("query", "reject") and not comment:
        who = "the contractor knows what to change" if by == "client" else "the raiser knows why"
        raise BusinessRuleError(f"Add a comment so {who}.")
    try:
        target = rules.next_status(status=variation.status, decision=decision, by=by)
    except rules.TransitionError as exc:
        conflict = ConflictError(str(exc))
        conflict.code = "invalid_transition"
        raise conflict from exc
    project = _locked_project(db, variation)
    before = variation.status
    variation.status = target.value
    if target in (S.APPROVED, S.REJECTED):
        variation.decided_by = user.id
        variation.decided_at = clock.utcnow()
    seen = by == "client" or variation.sent_to_client_at is not None
    _event(variation, user, _PAST[decision], before, comment, client_visible=seen)
    audit.record(
        db,
        AuditAction.VARIATION_CLIENT_DECIDED if by == "client" else AuditAction.VARIATION_DECIDED,
        meta=meta,
        actor_id=user.id,
        target_type="variation_order",
        target_id=variation.id,
        details={"number": variation.number, "decision": decision, "from": before, "to": target.value},
    )
    if target == S.APPROVED:
        _apply(db, variation, project, user, meta)
    _notify_decision(db, variation, project, user, decision, comment)
    db.commit()
    db.refresh(variation)
    if target == S.APPROVED:
        risk_service.rescore_after_report(db, project)  # the contract and programme changed
        cost_service.check_after_change(db, project)
    return variation


def _locked_project(db: Session, variation: VariationOrder) -> Project:
    project = db.scalars(
        select(Project).where(Project.id == variation.project_id).with_for_update(of=Project)
    ).one()
    return project


def _apply(db: Session, variation: VariationOrder, project: Project, actor: User, meta: RequestMeta) -> None:
    """TC-10: change the contract value, the budget line, the task and the planned end, audited."""
    contract = variation.contract_change or ZERO
    budget = variation.budget_change or ZERO
    line = db.scalars(
        select(BudgetLine).where(BudgetLine.section_id == variation.section_id).with_for_update()
    ).first()
    if line is None:
        raise ConflictError("The variation's BOQ section has no budget line.")
    if project.contract_value + contract <= ZERO or line.budget_amount + budget < ZERO:
        raise ConflictError("The contract or budget has changed since pricing; the QS must price it again.")
    before = {
        "contract_value": str(project.contract_value),
        "budget_line": str(line.budget_amount),
        "planned_end": project.planned_end.isoformat(),
    }
    project.contract_value += contract
    line.budget_amount += budget
    days = timedelta(days=variation.time_impact_days)
    project.planned_end += days
    task = db.get(Task, variation.task_id) if variation.task_id else None
    if task is not None and days:
        before["task_end"] = task.planned_end.isoformat()
        task.planned_end += days
    after = {
        "contract_value": str(project.contract_value),
        "budget_line": str(line.budget_amount),
        "planned_end": project.planned_end.isoformat(),
        **({"task_end": task.planned_end.isoformat()} if task is not None and days else {}),
    }
    audit.record(
        db,
        AuditAction.VARIATION_APPLIED,
        meta=meta,
        actor_id=actor.id,
        target_type="project",
        target_id=project.id,
        details={
            "variation": variation.number,
            "before": before,
            "after": after,
            **(
                {"boq_item": str(variation.boq_item_id), "extra_quantity": str(variation.quantity_change)}
                if variation.boq_item_id
                else {}
            ),
        },
    )


def _notify_decision(
    db: Session, variation: VariationOrder, project: Project, actor: User, decision: str, comment: str | None
) -> None:
    people = {variation.raised_by}
    if variation.priced_by:
        people.add(variation.priced_by)
    if actor.role == Role.CLIENT.value:  # the client's answer: every PM and QS on the site
        people |= {
            p.id
            for p in notification_service.site_people(
                db, project.site_id, {Role.PROJECT_MANAGER, Role.QUANTITY_SURVEYOR}
            )
        }
    people.discard(actor.id)
    verb = _PAST[decision]
    who = "the client" if actor.role == Role.CLIENT.value else actor.full_name
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=person,
                kind=f"variation_{verb}",
                title=f"{variation.number} {verb} by {who}",
                body=comment or variation.title,
                link=f"/variations/{variation.id}",
                project_id=project.id,
                dedupe_key=f"variation-decided:{variation.id}:{len(variation.events)}",
            )
            for person in sorted(people)
        ],
    )


# --- Company Admin: the BR-09 limit ---------------------------------------------------------------------


def list_limits(db: Session) -> list[ProjectLimitOut]:
    projects = db.scalars(select(Project).order_by(Project.code)).all()
    return [
        ProjectLimitOut(
            project_id=p.id,
            code=p.code,
            name=p.name,
            site_code=p.site.code,
            status=p.status,
            variation_limit=p.variation_limit,
        )
        for p in projects
    ]


def set_limit(
    db: Session, admin: User, project_id: uuid.UUID, data: ProjectLimitIn, *, meta: RequestMeta
) -> ProjectLimitOut:
    """Only the Company Admin changes a project's BR-09 limit; every change is audited with the reason.

    Variations already routed keep the limit they were routed with (``limit_applied``); the new limit
    applies to the next pricing.
    """
    project = db.scalars(select(Project).where(Project.id == project_id).with_for_update(of=Project)).first()
    if project is None:
        raise NotFoundError("Project not found.")
    before = project.variation_limit
    limit = money(data.variation_limit)
    if before == limit:
        raise BusinessRuleError("That is already the project's variation limit.")
    project.variation_limit = limit
    audit.record(
        db,
        AuditAction.VARIATION_LIMIT_CHANGED,
        meta=meta,
        actor_id=admin.id,
        target_type="project",
        target_id=project.id,
        details={
            "project": project.code,
            "from": str(before),
            "to": str(limit),
            "reason": data.reason,
        },
    )
    db.commit()
    db.refresh(project)
    return ProjectLimitOut(
        project_id=project.id,
        code=project.code,
        name=project.name,
        site_code=project.site.code,
        status=project.status,
        variation_limit=project.variation_limit,
    )
