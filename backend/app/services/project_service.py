"""Projects, BOQ and budget lines. Every read goes through the user's site scope (BR-03)."""

import uuid
from decimal import Decimal

from sqlalchemy import Subquery, delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.permissions import ROLE_LABELS, Role
from app.core.scoping import accessible_site_ids, ensure_site_access, scope_to_user_sites
from app.models import (
    BoqItem,
    BoqSection,
    BudgetLine,
    MaterialRequest,
    ProgressClaim,
    Project,
    ProjectStatus,
    RequestStatus,
    Site,
    User,
    VariationOrder,
)
from app.models.user import user_site_assignments
from app.rules.variations import VariationStatus
from app.schemas.auth import SiteSummary
from app.schemas.project import (
    MAX_PROJECT_DAYS,
    BoqItemOut,
    BoqOut,
    BoqSectionOut,
    CellErrorOut,
    ImportReport,
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
    RowResultOut,
    SectionPreview,
    SectionTotals,
    TeamMember,
)
from app.services import audit
from app.services.audit import AuditAction, RequestMeta
from app.services.boq_import import ParseResult

ZERO = Decimal("0.00")


def _totals_subquery() -> Subquery:
    return (
        select(
            BoqItem.project_id.label("project_id"),
            func.coalesce(func.sum(BoqItem.amount), 0).label("boq_total"),
            func.count(BoqItem.id).label("item_count"),
        )
        .group_by(BoqItem.project_id)
        .subquery()
    )


def _budget_subquery() -> Subquery:
    return (
        select(
            BudgetLine.project_id.label("project_id"),
            func.coalesce(func.sum(BudgetLine.budget_amount), 0).label("budget_total"),
        )
        .group_by(BudgetLine.project_id)
        .subquery()
    )


def _variations_subquery() -> Subquery:
    """Approved variations' contract change per project (Phase 8)."""
    return (
        select(
            VariationOrder.project_id.label("project_id"),
            func.coalesce(func.sum(VariationOrder.contract_change), 0).label("variations_total"),
        )
        .where(VariationOrder.status == VariationStatus.APPROVED.value)
        .group_by(VariationOrder.project_id)
        .subquery()
    )


def _summary(
    project: Project,
    boq_total: Decimal | None,
    budget_total: Decimal | None,
    items: int | None,
    variations_total: Decimal | None = None,
) -> dict[str, object]:
    return {
        "id": project.id,
        "code": project.code,
        "name": project.name,
        "site": SiteSummary.model_validate(project.site),
        "client_name": project.client_name,
        "project_type": project.project_type,
        "status": project.status,
        "contract_value": project.contract_value,
        "start_date": project.start_date,
        "planned_end": project.planned_end,
        "boq_total": Decimal(boq_total or 0).quantize(Decimal("0.01")),
        "budget_total": Decimal(budget_total or 0).quantize(Decimal("0.01")),
        "item_count": int(items or 0),
        "variations_total": Decimal(variations_total or 0).quantize(Decimal("0.01")),
    }


def list_projects(
    db: Session, user: User, *, status: ProjectStatus | None = None, query: str | None = None
) -> list[ProjectSummary]:
    totals = _totals_subquery()
    budgets = _budget_subquery()
    varied = _variations_subquery()
    stmt = (
        select(
            Project,
            totals.c.boq_total,
            budgets.c.budget_total,
            totals.c.item_count,
            varied.c.variations_total,
        )
        .outerjoin(totals, totals.c.project_id == Project.id)
        .outerjoin(budgets, budgets.c.project_id == Project.id)
        .outerjoin(varied, varied.c.project_id == Project.id)
    )
    stmt = scope_to_user_sites(stmt, Project.site_id, user)
    if status is not None:
        stmt = stmt.where(Project.status == status.value)
    if query:
        # Escape LIKE wildcards so a search for "50%" matches the text, not a pattern.
        escaped = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                *(
                    column.ilike(pattern, escape="\\")
                    for column in (Project.name, Project.code, Project.client_name)
                )
            )
        )
    rows = db.execute(stmt.order_by(Project.start_date.desc(), Project.code)).all()
    return [
        ProjectSummary.model_validate(_summary(p, boq, budget, items, var))
        for p, boq, budget, items, var in rows
    ]


def get_project(db: Session, user: User, project_id: uuid.UUID) -> Project:
    """404 for both "does not exist" and "not on your sites", so existence never leaks."""
    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    allowed = accessible_site_ids(user)
    if allowed is not None and project.site_id not in allowed:
        raise NotFoundError("Project not found.")
    return project


def _section_totals(db: Session, project: Project) -> list[SectionTotals]:
    stmt = (
        select(
            BoqSection,
            func.count(BoqItem.id),
            func.coalesce(func.sum(BoqItem.amount), 0),
            BudgetLine.id,
            BudgetLine.budget_amount,
        )
        .join(BudgetLine, BudgetLine.section_id == BoqSection.id)
        .outerjoin(BoqItem, BoqItem.section_id == BoqSection.id)
        .where(BoqSection.project_id == project.id)
        .group_by(BoqSection.id, BudgetLine.id)
        .order_by(BoqSection.position)
    )
    varied = dict(
        db.execute(
            select(VariationOrder.section_id, func.sum(VariationOrder.contract_change))
            .where(
                VariationOrder.project_id == project.id,
                VariationOrder.status == VariationStatus.APPROVED.value,
            )
            .group_by(VariationOrder.section_id)
        ).all()
    )
    return [
        SectionTotals(
            id=section.id,
            code=section.code,
            name=section.name,
            item_count=count,
            amount=Decimal(amount).quantize(Decimal("0.01")),
            budget_line_id=line_id,
            budget_amount=budget,
            variation_amount=Decimal(varied.get(section.id) or 0).quantize(Decimal("0.01")),
        )
        for section, count, amount, line_id, budget in db.execute(stmt).all()
    ]


def _team(db: Session, project: Project) -> list[TeamMember]:
    stmt = (
        select(User)
        .join(user_site_assignments, user_site_assignments.c.user_id == User.id)
        .where(user_site_assignments.c.site_id == project.site_id, User.is_active.is_(True))
        .order_by(User.role, User.full_name)
    )
    return [
        TeamMember(id=u.id, full_name=u.full_name, role=Role(u.role), role_label=ROLE_LABELS[Role(u.role)])
        for u in db.scalars(stmt).all()
    ]


def project_detail(db: Session, project: Project) -> ProjectDetail:
    sections = _section_totals(db, project)
    boq_total = sum((s.amount for s in sections), ZERO)
    budget_total = sum((s.budget_amount for s in sections), ZERO)
    items = sum(s.item_count for s in sections)
    variations = sum((s.variation_amount for s in sections), ZERO)
    return ProjectDetail.model_validate(
        {
            **_summary(project, boq_total, budget_total, items, variations),
            "description": project.description,
            "planned_crew": project.planned_crew,
            "contract_locked": contract_locked(db, project),
            "sections": sections,
            "team": _team(db, project),
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }
    )


def create_project(db: Session, data: ProjectCreate, *, actor: User, meta: RequestMeta) -> Project:
    ensure_site_access(actor, data.site_id)  # a PM can only open projects on their own sites
    site = db.get(Site, data.site_id)
    if site is None:
        raise NotFoundError("Site not found.")
    if not site.is_active:
        raise BusinessRuleError("This site is closed. Reopen it before adding a project.")
    project = Project(**data.model_dump(mode="python"))
    project.project_type = data.project_type.value
    project.status = data.status.value
    db.add(project)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("A project with this code already exists.") from exc
    audit.record(
        db,
        AuditAction.PROJECT_CREATED,
        meta=meta,
        actor_id=actor.id,
        target_type="project",
        target_id=project.id,
        details={"code": project.code, "site": site.code},
    )
    db.commit()
    db.refresh(project)
    return project


# The contract's price and completion date. Once work is under way they change only through approved
# variations, so every change is priced by the QS, routed by BR-09 and audited with before and after.
CONTRACT_FIELDS = frozenset({"contract_value", "planned_end"})


def contract_locked(db: Session, project: Project) -> bool:
    """True once the project is past planning, or has any claim or variation."""
    if project.status != ProjectStatus.PLANNING.value:
        return True
    has_claim = db.scalar(select(ProgressClaim.id).where(ProgressClaim.project_id == project.id).limit(1))
    has_variation = db.scalar(
        select(VariationOrder.id).where(VariationOrder.project_id == project.id).limit(1)
    )
    return has_claim is not None or has_variation is not None


def update_project(
    db: Session, project: Project, data: ProjectUpdate, *, actor: User, meta: RequestMeta
) -> Project:
    changes = data.model_dump(exclude_unset=True, mode="python")
    for key in ("project_type", "status"):
        if changes.get(key) is not None:
            changes[key] = changes[key].value
    start = changes.get("start_date", project.start_date)
    end = changes.get("planned_end", project.planned_end)
    if start is None or end is None or end < start:
        raise BusinessRuleError("The planned end date must be on or after the start date.")
    if (end - start).days > MAX_PROJECT_DAYS:
        raise BusinessRuleError("A project can run for at most 15 years.")
    for required in ("name", "client_name", "project_type", "status", "contract_value"):
        if required in changes and changes[required] is None:
            raise BusinessRuleError(f"{required.replace('_', ' ').capitalize()} cannot be empty.")
    changed = {k: v for k, v in changes.items() if getattr(project, k) != v}
    locked = sorted(set(changed) & CONTRACT_FIELDS)
    if locked and contract_locked(db, project):
        error = BusinessRuleError(
            "Once a project is under way, its contract value and planned end change only through approved "
            "variations (BR-09)."
        )
        error.code = "contract_locked"
        raise error
    for key, value in changed.items():
        setattr(project, key, value)
    if changed:
        audit.record(
            db,
            AuditAction.PROJECT_UPDATED,
            meta=meta,
            actor_id=actor.id,
            target_type="project",
            target_id=project.id,
            details={"fields": sorted(changed), "status": changed.get("status")},
        )
        db.commit()
        db.refresh(project)
    return project


# --- BOQ ------------------------------------------------------------------------------------


def get_boq(db: Session, project: Project) -> BoqOut:
    totals = {s.id: s for s in _section_totals(db, project)}
    sections = db.scalars(
        select(BoqSection).where(BoqSection.project_id == project.id).order_by(BoqSection.position)
    ).all()
    requested = dict(
        db.execute(
            select(MaterialRequest.boq_item_id, func.sum(MaterialRequest.quantity))
            .where(
                MaterialRequest.project_id == project.id,
                MaterialRequest.status.not_in((RequestStatus.REJECTED.value, RequestStatus.CANCELLED.value)),
            )
            .group_by(MaterialRequest.boq_item_id)
        ).all()
    )

    def item_out(item: BoqItem) -> BoqItemOut:
        asked = Decimal(requested.get(item.id) or 0)
        return BoqItemOut(
            id=item.id,
            item_code=item.item_code,
            description=item.description,
            unit=item.unit,
            quantity=item.quantity,
            requested_quantity=asked,
            remaining_quantity=max(item.quantity - asked, ZERO),
            rate=item.rate,
            amount=item.amount,
        )

    out = [
        BoqSectionOut(**totals[s.id].model_dump(), items=[item_out(item) for item in s.items])
        for s in sections
    ]
    return BoqOut(
        project_id=project.id,
        sections=out,
        boq_total=sum((s.amount for s in out), ZERO),
        budget_total=sum((s.budget_amount for s in out), ZERO),
        variations_total=sum((s.variation_amount for s in out), ZERO),
        item_count=sum(s.item_count for s in out),
    )


def import_boq(
    db: Session,
    project: Project,
    parsed: ParseResult,
    *,
    file_name: str,
    dry_run: bool,
    actor: User,
    meta: RequestMeta,
) -> ImportReport:
    existing = db.scalar(select(func.count(BoqItem.id)).where(BoqItem.project_id == project.id)) or 0
    imported = False
    # Material requests point at BOQ items, and replacing the BOQ would orphan them. Once any exist,
    # the BOQ changes through variations (Phase 8) instead. Checked on the dry run too, so the QS
    # learns this before preparing a file.
    if db.scalar(select(MaterialRequest.id).where(MaterialRequest.project_id == project.id).limit(1)):
        raise BusinessRuleError(
            "This BOQ cannot be replaced: material requests already refer to its items. "
            "Changes to the BOQ go through variations."
        )

    if not dry_run and parsed.is_valid:
        # Replacing a BOQ is all-or-nothing inside one transaction.
        db.execute(delete(BoqSection).where(BoqSection.project_id == project.id))
        sections: dict[str, BoqSection] = {}
        for position, summary in enumerate(parsed.sections, start=1):
            section = BoqSection(
                project_id=project.id, code=summary.code, name=summary.name, position=position
            )
            section.budget_line = BudgetLine(project_id=project.id, budget_amount=summary.budget)
            db.add(section)
            sections[summary.code] = section
        db.flush()
        for position, item in enumerate(parsed.items, start=1):
            db.add(
                BoqItem(
                    project_id=project.id,
                    section_id=sections[item.section_code].id,
                    item_code=item.item_code,
                    description=item.description,
                    unit=item.unit,
                    quantity=item.quantity,
                    rate=item.rate,
                    amount=item.amount,
                    position=position,
                )
            )
        audit.record(
            db,
            AuditAction.BOQ_IMPORTED,
            meta=meta,
            actor_id=actor.id,
            target_type="project",
            target_id=project.id,
            details={
                "file": file_name[:120],
                "items": len(parsed.items),
                "sections": len(parsed.sections),
                "replaced_items": existing,
                "boq_total": str(sum((s.amount for s in parsed.sections), ZERO)),
            },
        )
        db.commit()
        imported = True

    rows = parsed.rows
    return ImportReport(
        file_name=file_name[:120],
        imported=imported,
        dry_run=dry_run,
        total_rows=len(rows),
        ok_rows=sum(r.status == "ok" for r in rows),
        error_rows=parsed.error_count,
        skipped_rows=sum(r.status == "skipped" for r in rows),
        has_budget_rates=parsed.has_budget_rates,
        replaces_items=existing,
        boq_total=sum((s.amount for s in parsed.sections), ZERO),
        budget_total=sum((s.budget for s in parsed.sections), ZERO),
        sections=[
            SectionPreview(code=s.code, name=s.name, items=s.items, amount=s.amount, budget=s.budget)
            for s in parsed.sections
        ],
        rows=[
            RowResultOut(
                row=r.row,
                status=r.status,
                section_code=r.section_code,
                item_code=r.item_code,
                description=r.description,
                errors=[CellErrorOut(column=e.column, message=e.message) for e in r.errors],
            )
            for r in rows
        ],
    )


def update_budget_line(
    db: Session, project: Project, line_id: uuid.UUID, amount: Decimal, *, actor: User, meta: RequestMeta
) -> BudgetLine:
    line = db.scalar(select(BudgetLine).where(BudgetLine.id == line_id, BudgetLine.project_id == project.id))
    if line is None:
        raise NotFoundError("Budget line not found.")
    before = line.budget_amount
    if before != amount:
        line.budget_amount = amount
        audit.record(
            db,
            AuditAction.BUDGET_LINE_UPDATED,
            meta=meta,
            actor_id=actor.id,
            target_type="project",
            target_id=project.id,
            details={"section": line.section.code, "from": str(before), "to": str(amount)},
        )
        db.commit()
    return line
