"""Progress claims (Phase 8, BR-08).

Workflow C in the build guide:
    1. The QS certifies a percentage complete for each BOQ section (never below the last approved
       claim). The claim is calculated, never typed in (``app.rules.claims``).
    2. The PM approves it, or returns it with a comment (the QS then makes a new claim).
    3. Approved claims count as previous claims and are what the client sees (Phase 12). The QS
       records the payment date when the client pays.

One claim waits for the PM at a time per project (a unique index), so "previous claims" cannot
change between a claim being made and being approved. Creating a claim locks the project row, so two
QSs cannot both use the same figures. Segregation of duties comes from the roles: only a QS submits
(``claims:manage``) and only a PM approves (``claims:approve``).
"""

from __future__ import annotations

import uuid
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import Permission, Role, has_permission
from app.models import BoqSection, ClaimStatus, ProgressClaim, ProgressClaimLine, Project, User
from app.rules import claims as rules
from app.rules.materials import ZERO, RuleResult, money
from app.schemas.contract import (
    ClaimAction,
    ClaimCheckOut,
    ClaimDecisionIn,
    ClaimFiguresOut,
    ClaimIn,
    ClaimOut,
    ClaimPaymentIn,
    ClaimSectionOut,
    ClaimsOverview,
    RuleOut,
)
from app.services import audit, cost_service, notification_service, project_service
from app.services.audit import AuditAction, RequestMeta
from app.services.materials_service import next_number
from app.services.notification_service import NewNotification

COUNTED = (ClaimStatus.APPROVED.value, ClaimStatus.PAID.value)  # "previous claims" (BR-08)


def _can(user: User, permission: Permission) -> bool:
    return has_permission(Role(user.role), permission)


def _counted_claims(db: Session, project_id: uuid.UUID) -> list[ProgressClaim]:
    return list(
        db.scalars(
            select(ProgressClaim)
            .where(ProgressClaim.project_id == project_id, ProgressClaim.status.in_(COUNTED))
            .order_by(ProgressClaim.submitted_at)
        ).all()
    )


def _previous_pcts(counted: list[ProgressClaim]) -> dict[uuid.UUID, Decimal]:
    """Each section's certified percentage on the latest approved (or paid) claim."""
    if not counted:
        return {}
    return {line.section_id: line.certified_pct for line in counted[-1].lines}


def _sections(db: Session, project: Project) -> list[BoqSection]:
    return list(
        db.scalars(
            select(BoqSection).where(BoqSection.project_id == project.id).order_by(BoqSection.position)
        ).all()
    )


def _progress(
    db: Session, project: Project, data: ClaimIn
) -> tuple[list[rules.SectionProgress], rules.ClaimFigures]:
    sections = _sections(db, project)
    by_id = {s.id: s for s in sections}
    wanted = {item.section_id: item.certified_pct for item in data.sections}
    if len(wanted) != len(data.sections):
        raise BusinessRuleError("Each section can appear once.")
    if set(wanted) - set(by_id):
        raise BusinessRuleError("One of the sections is not in this project's BOQ.")
    counted = _counted_claims(db, project.id)
    previous = _previous_pcts(counted)
    values = cost_service.section_contract_values(db, project.id)
    progress = [
        rules.SectionProgress(
            section_id=s.id,
            value=values.get(s.id, ZERO),
            # Sections left out keep their last approved figure.
            certified_pct=wanted.get(s.id, previous.get(s.id, ZERO)),
            previous_pct=previous.get(s.id, ZERO),
        )
        for s in sections
    ]
    figures = rules.calculate(
        contract_value=project.contract_value,
        sections=progress,
        previous_claims=sum((c.amount for c in counted), ZERO),
    )
    return progress, figures


def _figures_out(f: rules.ClaimFigures, contract_value: Decimal) -> ClaimFiguresOut:
    return ClaimFiguresOut(
        contract_value=contract_value,
        certified_pct=f.certified_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
        certified_value=money(f.certified_value),
        retention=money(f.retention),
        retention_rate=rules.RETENTION,
        previous_claims=money(f.previous_claims),
        amount=money(f.amount),
    )


def _rule_out(r: RuleResult) -> RuleOut:
    return RuleOut(rule=r.rule, severity=r.severity, message=r.message, facts=r.facts)


def _project_for(db: Session, user: User, project_id: uuid.UUID, *, lock: bool = False) -> Project:
    project = project_service.get_project(db, user, project_id)  # 404 outside the user's sites
    if lock:
        db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    return project


# --- Reading --------------------------------------------------------------------------------------------


def actions_for(claim: ProgressClaim, user: User) -> list[ClaimAction]:
    actions: list[ClaimAction] = []
    if claim.status == ClaimStatus.SUBMITTED.value and _can(user, Permission.CLAIMS_APPROVE):
        actions += ["approve", "return"]
    if claim.status == ClaimStatus.APPROVED.value and _can(user, Permission.CLAIMS_MANAGE):
        actions.append("record_payment")
    return actions


def claim_out(claim: ProgressClaim, user: User) -> ClaimOut:
    figures = rules.ClaimFigures(
        certified_pct=claim.certified_pct,
        certified_value=claim.certified_value,
        retention=claim.retention,
        previous_claims=claim.previous_claims,
        amount=claim.amount,
    )
    return ClaimOut(
        id=claim.id,
        number=claim.number,
        project_id=claim.project_id,
        status=claim.status,
        figures=_figures_out(figures, claim.contract_value),
        notes=claim.notes,
        submitted_by=claim.submitter.full_name,
        submitted_at=claim.submitted_at,
        decided_by=claim.decider.full_name if claim.decider else None,
        decided_at=claim.decided_at,
        decision_comment=claim.decision_comment,
        paid_on=claim.paid_on,
        lines=[
            ClaimSectionOut(
                section_id=line.section_id,
                code=line.section.code,
                name=line.section.name,
                section_value=line.section_value,
                previous_pct=line.previous_pct,
                certified_pct=line.certified_pct,
            )
            for line in claim.lines
        ],
        actions=actions_for(claim, user),
    )


def overview(db: Session, user: User, project_id: uuid.UUID) -> ClaimsOverview:
    project = _project_for(db, user, project_id)
    claims = db.scalars(
        select(ProgressClaim)
        .where(ProgressClaim.project_id == project.id)
        .order_by(ProgressClaim.submitted_at.desc())
    ).all()
    counted = [c for c in reversed(claims) if c.status in COUNTED]
    previous = _previous_pcts(counted)
    values = cost_service.section_contract_values(db, project.id)
    waiting = any(c.status == ClaimStatus.SUBMITTED.value for c in claims)
    return ClaimsOverview(
        claims=[claim_out(c, user) for c in claims],
        sections=[
            ClaimSectionOut(
                section_id=s.id,
                code=s.code,
                name=s.name,
                section_value=values.get(s.id, ZERO),
                previous_pct=previous.get(s.id, ZERO),
            )
            for s in _sections(db, project)
        ],
        claimed_to_date=money(sum((c.amount for c in counted), ZERO)),
        retention_held=money(counted[-1].retention if counted else ZERO),
        paid_to_date=money(sum((c.amount for c in counted if c.status == ClaimStatus.PAID.value), ZERO)),
        can_create=_can(user, Permission.CLAIMS_MANAGE) and not waiting,
    )


def get_claim(db: Session, user: User, claim_id: uuid.UUID, *, lock: bool = False) -> ProgressClaim:
    stmt = select(ProgressClaim).where(ProgressClaim.id == claim_id)
    claim = db.scalars(stmt.with_for_update(of=ProgressClaim) if lock else stmt).first()
    if claim is None:
        raise NotFoundError("Claim not found.")
    try:
        project_service.get_project(db, user, claim.project_id)
    except NotFoundError as exc:
        raise NotFoundError("Claim not found.") from exc
    return claim


# --- Creating -------------------------------------------------------------------------------------------


def check(db: Session, user: User, project_id: uuid.UUID, data: ClaimIn) -> ClaimCheckOut:
    """The calculation and its problems for a draft claim, nothing saved."""
    project = _project_for(db, user, project_id)
    progress, figures = _progress(db, project, data)
    return ClaimCheckOut(
        figures=_figures_out(figures, project.contract_value),
        problems=[_rule_out(p) for p in rules.check(progress, figures)],
    )


def create(
    db: Session, user: User, project_id: uuid.UUID, data: ClaimIn, *, meta: RequestMeta
) -> ProgressClaim:
    project = _project_for(db, user, project_id, lock=True)
    if db.scalar(
        select(ProgressClaim.id).where(
            ProgressClaim.project_id == project.id, ProgressClaim.status == ClaimStatus.SUBMITTED.value
        )
    ):
        raise ConflictError("A claim on this project is already waiting for the project manager.")
    progress, figures = _progress(db, project, data)
    problems = rules.check(progress, figures)
    if problems:
        error = BusinessRuleError(problems[0].message)
        error.code = "claim_rejected"
        raise error

    now = clock.utcnow()
    claim = ProgressClaim(
        number=next_number(db, "PC"),
        project_id=project.id,
        status=ClaimStatus.SUBMITTED.value,
        contract_value=project.contract_value,
        certified_pct=figures.certified_pct.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP),
        certified_value=figures.certified_value,
        retention=figures.retention,
        previous_claims=figures.previous_claims,
        amount=figures.amount,
        notes=data.notes,
        submitted_by=user.id,
        submitted_at=now,
    )
    claim.lines = [
        ProgressClaimLine(
            section_id=p.section_id,
            section_value=p.value,
            certified_pct=p.certified_pct,
            previous_pct=p.previous_pct,
            position=i,
        )
        for i, p in enumerate(progress)
    ]
    db.add(claim)
    db.flush()
    audit.record(
        db,
        AuditAction.CLAIM_SUBMITTED,
        meta=meta,
        actor_id=user.id,
        target_type="progress_claim",
        target_id=claim.id,
        details={
            "number": claim.number,
            "project": project.code,
            "certified_value": str(claim.certified_value),
            "retention": str(claim.retention),
            "amount": str(claim.amount),
        },
    )
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=pm.id,
                kind="claim_submitted",
                title=f"{claim.number} waiting for approval",
                body=f"{project.code}: LKR {claim.amount:,.2f} after retention, certified "
                f"{figures.certified_pct.quantize(Decimal('0.1'))}% by {user.full_name}.",
                link=f"/projects/{project.id}/claims",
                project_id=project.id,
                dedupe_key=f"claim-submitted:{claim.id}",
            )
            for pm in notification_service.site_people(db, project.site_id, {Role.PROJECT_MANAGER})
        ],
    )
    db.commit()
    db.refresh(claim)
    return claim


# --- Deciding and paying ------------------------------------------------------------------------------


def decide(
    db: Session, user: User, claim_id: uuid.UUID, data: ClaimDecisionIn, *, meta: RequestMeta
) -> ProgressClaim:
    claim = get_claim(db, user, claim_id, lock=True)
    if not _can(user, Permission.CLAIMS_APPROVE):
        raise ForbiddenError("Only a project manager approves claims.")
    if claim.status != ClaimStatus.SUBMITTED.value:
        raise ConflictError("This claim is not waiting for a decision.")
    if data.decision == "return" and not data.comment:
        raise BusinessRuleError("Add a comment so the QS knows what to change.")
    previous = claim.status
    claim.status = ClaimStatus.APPROVED.value if data.decision == "approve" else ClaimStatus.RETURNED.value
    claim.decided_by = user.id
    claim.decided_at = clock.utcnow()
    claim.decision_comment = data.comment
    audit.record(
        db,
        AuditAction.CLAIM_DECIDED,
        meta=meta,
        actor_id=user.id,
        target_type="progress_claim",
        target_id=claim.id,
        details={"number": claim.number, "decision": data.decision, "from": previous, "to": claim.status},
    )
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=claim.submitted_by,
                kind=f"claim_{claim.status}",
                title=f"{claim.number} {'approved' if data.decision == 'approve' else 'returned'}",
                body=f"{user.full_name}: {data.comment}"
                if data.comment
                else f"Decision by {user.full_name}.",
                link=f"/projects/{claim.project_id}/claims",
                project_id=claim.project_id,
                dedupe_key=f"claim-decided:{claim.id}",
            )
        ],
    )
    db.commit()
    db.refresh(claim)
    return claim


def record_payment(
    db: Session, user: User, claim_id: uuid.UUID, data: ClaimPaymentIn, *, meta: RequestMeta
) -> ProgressClaim:
    claim = get_claim(db, user, claim_id, lock=True)
    if not _can(user, Permission.CLAIMS_MANAGE):
        raise ForbiddenError("Only a quantity surveyor records claim payments.")
    if claim.status != ClaimStatus.APPROVED.value:
        raise ConflictError("Only an approved, unpaid claim can be marked paid.")
    today = clock.site_today()
    approved_on = claim.decided_at.astimezone(clock.SITE_TIME_ZONE).date() if claim.decided_at else today
    if not approved_on <= data.paid_on <= today:
        raise BusinessRuleError(
            f"The payment date must be between the approval ({approved_on:%d %b %Y}) and today."
        )
    claim.status = ClaimStatus.PAID.value
    claim.paid_on = data.paid_on
    claim.paid_recorded_by = user.id
    audit.record(
        db,
        AuditAction.CLAIM_PAID,
        meta=meta,
        actor_id=user.id,
        target_type="progress_claim",
        target_id=claim.id,
        details={"number": claim.number, "paid_on": data.paid_on.isoformat(), "amount": str(claim.amount)},
    )
    db.commit()
    db.refresh(claim)
    return claim
