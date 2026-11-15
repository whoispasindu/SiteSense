"""The client portal (Phase 12): what a client sees, and what the project manager shares with them.

Clients reach only the projects the Company Admin linked them to (``client_access``), never through a
site, and never a cancelled one: anything else answers 404, exactly like a project that does not exist.

Every response is built field by field into the client schemas in ``app.schemas.portal``: there is no
path from an internal model or schema to a client response, so a budget, cost, rate, risk score or
internal comment cannot leak by accident.

Photos are private until the project manager shares them. A shared photo leaves the server without
any metadata (``photos.without_metadata``).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import NotFoundError
from app.models import (
    ClaimStatus,
    DailyReport,
    ProgressClaim,
    Project,
    ReportPhoto,
    Task,
    User,
    VariationOrder,
)
from app.rules.variations import VariationStatus
from app.schemas.portal import (
    ClientClaim,
    ClientClaims,
    ClientHandover,
    ClientHandoverChange,
    ClientMilestone,
    ClientPhoto,
    ClientProgressPoint,
    ClientProject,
    ClientProjectCard,
    MilestoneStatus,
    PhotosShareIn,
    ProjectPhotoOut,
    ProjectPhotos,
    RetentionRelease,
)
from app.services import audit, client_access, handover_service, network_service, schedule_service
from app.services.audit import RequestMeta
from app.services.progress import actual_percent, planned_percent

PHOTO_LIMIT = 60


def add_months(day: date, months: int) -> date:
    """The same day ``months`` later, on the month's last day when it is shorter (31 Jan + 1 = 28 Feb)."""
    month_index = day.month - 1 + months
    year, month = day.year + month_index // 12, month_index % 12 + 1
    last = (date(year + month // 12, month % 12 + 1, 1) - date.resolution).day
    return date(year, month, min(day.day, last))


def retention_release(db: Session, project: Project) -> RetentionRelease:
    published = handover_service.latest_published(db, project.id)
    handover = published.handover_date if published else project.planned_end
    return RetentionRelease(
        defects_period_months=project.defects_period_months,
        handover_date=handover,
        handover_published=published is not None,
        expected_on=add_months(handover, project.defects_period_months),
    )


def retention_note(release: RetentionRelease) -> str:
    months = release.defects_period_months
    basis = "the expected handover" if release.handover_published else "the contract handover date"
    if months == 0:
        return (
            "Retention is held back from each claim and released at handover: "
            f"expected {release.expected_on:%d %B %Y}."
        )
    return (
        f"Retention is held back from each claim and released at the end of the {months}-month defects "
        f"period after handover: expected around {release.expected_on:%d %B %Y}, from {basis}."
    )


ZERO = Decimal("0.00")
CENT = Decimal("0.01")


# --- Access -----------------------------------------------------------------------------------------------


def client_project(db: Session, user: User, project_id: uuid.UUID) -> Project:
    """A project the client is linked to, or 404: the same answer for "missing" and "not yours"."""
    return client_access.project_for(db, user, project_id)


# --- The client's views -----------------------------------------------------------------------------------


def _variations_waiting(db: Session, project_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(VariationOrder.id)).where(
                VariationOrder.project_id == project_id,
                VariationOrder.status == VariationStatus.AWAITING_CLIENT.value,
            )
        )
        or 0
    )


def _card(db: Session, project: Project) -> ClientProjectCard:
    plans = [schedule_service.plan(t) for t in db.scalars(select(Task).where(Task.project_id == project.id))]
    published = handover_service.latest_published(db, project.id)
    return ClientProjectCard(
        id=project.id,
        code=project.code,
        name=project.name,
        location=project.site.location,
        status=project.status,
        planned_percent=round(planned_percent(plans, clock.site_today()), 1),
        actual_percent=round(actual_percent(plans), 1),
        handover_date=published.handover_date if published else project.planned_end,
        handover_published=published is not None,
        variations_waiting=_variations_waiting(db, project.id),
    )


def list_projects(db: Session, user: User) -> list[ClientProjectCard]:
    ids = client_access.project_ids(user)
    if not ids:
        return []
    projects = db.scalars(select(Project).where(Project.id.in_(ids)).order_by(Project.name)).all()
    return [_card(db, p) for p in projects]


def _handover(db: Session, project: Project) -> ClientHandover:
    published = [r for r in handover_service.entries(db, project.id) if r.kind == "published"]
    latest = published[0] if published else None
    return ClientHandover(
        contract_end=project.planned_end,
        published_date=latest.handover_date if latest else None,
        reason=latest.reason if latest else None,
        published_at=latest.published_at if latest else None,
        history=[
            ClientHandoverChange(handover_date=r.handover_date, reason=r.reason, published_at=r.published_at)
            for r in published[1:]
        ],
    )


def _status(task: Task, forecast_finish: date | None, today: date) -> MilestoneStatus:
    if task.percent_complete >= 100:
        return "done"
    if forecast_finish is not None and forecast_finish > task.planned_end:
        return "late"
    if task.percent_complete <= 0 and task.planned_start > today:
        return "not_started"
    return "on_track"


def _milestones(db: Session, project: Project, published: date | None) -> list[ClientMilestone]:
    tasks = list(
        db.scalars(
            select(Task)
            .where(Task.project_id == project.id, Task.client_milestone.is_(True))
            .order_by(Task.planned_end, Task.position)
        )
    )
    if not tasks:
        return []
    try:
        forecasts = {t.task_id: t.forecast_finish for t in network_service.analyse(db, project).tasks}
    except Exception:  # without a readable network, milestones fall back to their planned dates
        forecasts = {}
    today = clock.site_today()
    out = []
    for task in tasks:
        forecast = forecasts.get(task.id)
        expected = task.actual_finish or forecast or task.planned_end
        if published is not None and task.actual_finish is None:
            expected = min(expected, published)  # never after the date the client was given
        out.append(
            ClientMilestone(
                name=task.milestone_name or task.name,
                planned_date=task.planned_end,
                expected_date=expected,
                completed_on=task.actual_finish,
                percent_complete=float(task.percent_complete),
                status=_status(task, forecast, today),
            )
        )
    return out


def _shared_photos(db: Session, project_id: uuid.UUID) -> list[ClientPhoto]:
    rows = db.execute(
        select(ReportPhoto, DailyReport.report_date)
        .join(DailyReport, DailyReport.id == ReportPhoto.report_id)
        .where(DailyReport.project_id == project_id, ReportPhoto.shared_with_client.is_(True))
        .order_by(DailyReport.report_date.desc(), ReportPhoto.position)
        .limit(PHOTO_LIMIT)
    ).all()
    return [
        ClientPhoto(id=photo.id, caption=photo.caption, taken_on=day, width=photo.width, height=photo.height)
        for photo, day in rows
    ]


def project_view(db: Session, user: User, project_id: uuid.UUID) -> ClientProject:
    project = client_project(db, user, project_id)
    card = _card(db, project)
    handover = _handover(db, project)
    progress = schedule_service.progress(db, project)
    return ClientProject(
        **card.model_dump(),
        start_date=project.start_date,
        handover=handover,
        progress=[
            ClientProgressPoint(date=p.date, planned=p.planned, actual=p.actual) for p in progress.points
        ],
        milestones=_milestones(db, project, handover.published_date),
        photos=_shared_photos(db, project.id),
    )


def claims_view(db: Session, user: User, project_id: uuid.UUID) -> ClientClaims:
    """Approved and paid claims only, with the contract value. Submitted or returned claims stay internal."""
    project = client_project(db, user, project_id)
    shown = (ClaimStatus.APPROVED.value, ClaimStatus.PAID.value)
    claims = list(
        db.scalars(
            select(ProgressClaim)
            .where(ProgressClaim.project_id == project.id, ProgressClaim.status.in_(shown))
            .order_by(ProgressClaim.decided_at.desc())
        )
    )
    variations = sum(
        (
            v.contract_change or ZERO
            for v in db.scalars(
                select(VariationOrder).where(
                    VariationOrder.project_id == project.id,
                    VariationOrder.status == VariationStatus.APPROVED.value,
                )
            )
        ),
        ZERO,
    )
    out = [
        ClientClaim(
            number=c.number,
            status="paid" if c.status == ClaimStatus.PAID.value else "approved",
            certified_pct=c.certified_pct.quantize(CENT, rounding=ROUND_HALF_UP),  # kept to 6 places inside
            certified_value=c.certified_value,
            retention=c.retention,
            previous_claims=c.previous_claims,
            amount=c.amount,
            approved_on=(c.decided_at or c.submitted_at).astimezone(clock.site_zone()).date(),
            paid_on=c.paid_on,
        )
        for c in claims
    ]
    release = retention_release(db, project)
    return ClientClaims(
        project_id=project.id,
        original_contract_value=project.contract_value - variations,
        approved_variations=variations,
        contract_value=project.contract_value,
        claimed_to_date=sum((c.amount for c in claims), ZERO),
        paid_to_date=sum((c.amount for c in claims if c.status == ClaimStatus.PAID.value), ZERO),
        # Retention is cumulative (5% of the value certified so far): the latest claim's figure is the total.
        retention_held=claims[0].retention if claims else ZERO,
        retention_release=release,
        retention_note=retention_note(release),
        claims=out,
    )


def shared_photo(db: Session, user: User, photo_id: uuid.UUID) -> ReportPhoto:
    """A photo the PM has shared, on one of the client's projects; 404 for anything else."""
    photo = db.get(ReportPhoto, photo_id)
    if photo is None or not photo.shared_with_client:
        raise NotFoundError("Photo not found.")
    try:
        client_project(db, user, photo.report.project_id)
    except NotFoundError as exc:
        raise NotFoundError("Photo not found.") from exc
    return photo


# --- The project manager shares photos ----------------------------------------------------------------


def project_photos(db: Session, project: Project, *, limit: int, offset: int) -> ProjectPhotos:
    base = (
        select(ReportPhoto, DailyReport.report_date)
        .join(DailyReport, DailyReport.id == ReportPhoto.report_id)
        .where(DailyReport.project_id == project.id)
    )
    total = db.scalar(base.with_only_columns(func.count(ReportPhoto.id))) or 0
    shared = (
        db.scalar(base.with_only_columns(func.count(ReportPhoto.id)).where(ReportPhoto.shared_with_client))
        or 0
    )
    rows = db.execute(
        base.order_by(DailyReport.report_date.desc(), ReportPhoto.position).limit(limit).offset(offset)
    ).all()
    return ProjectPhotos(
        items=[
            ProjectPhotoOut(
                id=photo.id,
                report_id=photo.report_id,
                report_date=day,
                caption=photo.caption,
                width=photo.width,
                height=photo.height,
                shared_with_client=photo.shared_with_client,
                shared_at=photo.shared_at,
            )
            for photo, day in rows
        ],
        total=int(total),
        shared=int(shared),
    )


def set_shared(
    db: Session, user: User, project: Project, data: PhotosShareIn, *, meta: RequestMeta
) -> ProjectPhotos:
    """Share (or unshare) photos of one project with its clients. All must belong to the project."""
    ids = list(dict.fromkeys(data.photo_ids))
    photos = list(
        db.scalars(
            select(ReportPhoto)
            .join(DailyReport, DailyReport.id == ReportPhoto.report_id)
            .where(ReportPhoto.id.in_(ids), DailyReport.project_id == project.id)
            .with_for_update(of=ReportPhoto)
        )
    )
    if len(photos) != len(ids):
        raise NotFoundError("Photo not found.")
    now = clock.utcnow()
    actor_id = user.id  # read before the loop: a lookup mid-way would flush a half-updated row
    changed = [p for p in photos if p.shared_with_client != data.shared]
    with db.no_autoflush:
        for photo in changed:
            photo.shared_with_client = data.shared
            photo.shared_by = actor_id if data.shared else None
            photo.shared_at = now if data.shared else None
    if changed:
        audit.record(
            db,
            audit.AuditAction.PHOTOS_CLIENT_SHARE_CHANGED,
            meta=meta,
            actor_id=actor_id,
            target_type="project",
            target_id=project.id,
            details={"shared": data.shared, "photos": sorted(str(p.id) for p in changed)},
        )
    db.commit()
    return project_photos(db, project, limit=PHOTO_LIMIT, offset=0)
