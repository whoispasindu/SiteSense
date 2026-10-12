"""Daily site reports. Access always goes through the report's project (site scoping, BR-03).

Rules:
- One report per project per site day (TC-03); a second one is refused with a link to the first.
- Reports cover today or up to ``MAX_BACKDATE_DAYS`` earlier, never the future or before the
  project starts, and only for projects that are running (active or on hold).
- The author may correct the report and add or remove photos on the day they submitted it.
- Task progress in a report updates the programme, like a progress update in the Schedule tab.
"""

import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.core.permissions import Permission, Role, has_permission
from app.core.scoping import scope_to_user_sites
from app.integrations.storage import Storage
from app.models import DailyReport, Project, ProjectStatus, ReportPhoto, ReportProgress, Site, Task, User
from app.schemas.report import (
    AuthorOut,
    PhotoOut,
    ReportCreate,
    ReportDetail,
    ReportList,
    ReportProgressOut,
    ReportStatus,
    ReportSummary,
    ReportUpdate,
    TodayStatus,
)
from app.services import audit, notification_service, photos, project_service, schedule_service, weather
from app.services.audit import AuditAction, RequestMeta
from app.services.notification_service import NewNotification

MAX_BACKDATE_DAYS = 7
OPEN_STATUSES = {ProjectStatus.ACTIVE.value, ProjectStatus.ON_HOLD.value}
PREVIEW_CHARS = 160
WEATHER_FIELDS = ("weather_summary", "temp_max_c", "temp_min_c", "rain_mm")


def _site_day(moment: datetime) -> date:
    return moment.astimezone(clock.SITE_TIME_ZONE).date()


def is_editable(report: DailyReport, user: User) -> bool:
    return report.author_id == user.id and _site_day(report.submitted_at) == clock.site_today()


def _author(user: User) -> AuthorOut:
    return AuthorOut(id=user.id, full_name=user.full_name)


def get_report(db: Session, user: User, report_id: uuid.UUID) -> tuple[DailyReport, Project]:
    report = db.get(DailyReport, report_id)
    if report is None:
        raise NotFoundError("Report not found.")
    try:
        project = project_service.get_project(db, user, report.project_id)
    except NotFoundError as exc:  # out of scope looks exactly like missing
        raise NotFoundError("Report not found.") from exc
    return report, project


def to_detail(report: DailyReport, project: Project, user: User, photo_limit: int) -> ReportDetail:
    return ReportDetail(
        id=report.id,
        project_id=report.project_id,
        project_name=project.name,
        report_date=report.report_date,
        author=_author(report.author),
        weather_summary=report.weather_summary,
        temp_max_c=report.temp_max_c,
        temp_min_c=report.temp_min_c,
        rain_mm=report.rain_mm,
        weather_source=report.weather_source,
        crew_count=report.crew_count,
        work_done=report.work_done,
        problems=report.problems,
        submitted_at=report.submitted_at,
        updated_at=report.updated_at,
        photos=[
            PhotoOut(
                id=p.id,
                caption=p.caption,
                width=p.width,
                height=p.height,
                size_bytes=p.size_bytes,
                created_at=p.created_at,
                shared_with_client=p.shared_with_client,
            )
            for p in report.photos
        ],
        progress=[
            ReportProgressOut(
                task_id=p.task_id,
                task_name=p.task_name,
                percent_before=p.percent_before,
                percent_after=p.percent_after,
            )
            for p in sorted(report.progress, key=lambda item: item.task_name)
        ],
        editable=is_editable(report, user),
        photo_limit=photo_limit,
    )


def list_reports(db: Session, project: Project, *, limit: int, offset: int) -> ReportList:
    photo_count = (
        select(func.count(ReportPhoto.id)).where(ReportPhoto.report_id == DailyReport.id).scalar_subquery()
    )
    progress_count = (
        select(func.count(ReportProgress.id))
        .where(ReportProgress.report_id == DailyReport.id)
        .scalar_subquery()
    )
    rows = db.execute(
        select(DailyReport, photo_count, progress_count)
        .where(DailyReport.project_id == project.id)
        .order_by(DailyReport.report_date.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count(DailyReport.id)).where(DailyReport.project_id == project.id)) or 0
    items = [
        ReportSummary(
            id=r.id,
            project_id=r.project_id,
            report_date=r.report_date,
            author=_author(r.author),
            weather_summary=r.weather_summary,
            rain_mm=r.rain_mm,
            crew_count=r.crew_count,
            work_done_preview=r.work_done[:PREVIEW_CHARS],
            has_problems=bool(r.problems),
            photo_count=int(photos_n or 0),
            progress_count=int(progress_n or 0),
            submitted_at=r.submitted_at,
        )
        for r, photos_n, progress_n in rows
    ]
    return ReportList(items=items, total=int(total))


def _check_date(project: Project, day: date) -> None:
    today = clock.site_today()
    if day > today:
        raise BusinessRuleError("A report cannot be dated in the future.")
    if day < today - timedelta(days=MAX_BACKDATE_DAYS):
        raise BusinessRuleError(f"Reports can be filed at most {MAX_BACKDATE_DAYS} days late.")
    if day < project.start_date:
        raise BusinessRuleError("A report cannot be dated before the project starts.")


def _existing(db: Session, project: Project, day: date) -> DailyReport | None:
    return db.scalar(
        select(DailyReport).where(DailyReport.project_id == project.id, DailyReport.report_date == day)
    )


def _duplicate(report: DailyReport) -> ConflictError:
    return ConflictError(
        f"A report for {report.report_date.strftime('%d %b %Y')} already exists. Open it to make changes.",
        details=[{"field": "report_date", "report_id": str(report.id)}],
    )


def _site_managers(db: Session, project: Project, roles: set[Role]) -> list[User]:
    return notification_service.site_people(db, project.site_id, roles)


def create_report(
    db: Session, project: Project, data: ReportCreate, *, actor: User, meta: RequestMeta
) -> DailyReport:
    if project.status not in OPEN_STATUSES:
        raise BusinessRuleError("Reports can only be filed for active or on-hold projects.")
    _check_date(project, data.report_date)
    if (existing := _existing(db, project, data.report_date)) is not None:
        raise _duplicate(existing)

    values = data.model_dump(exclude={"progress"})
    if all(values[name] is None for name in WEATHER_FIELDS):
        cached = weather.for_day(db, project.site_id, data.report_date)
        if cached is not None:
            values.update(
                weather_summary=cached.summary,
                temp_max_c=cached.temp_max_c,
                temp_min_c=cached.temp_min_c,
                rain_mm=cached.rain_mm,
                weather_source="forecast",
            )

    report = DailyReport(project_id=project.id, author_id=actor.id, submitted_at=clock.utcnow(), **values)
    db.add(report)

    tasks: dict[uuid.UUID, Task] = {}
    # Progress in a report changes the programme, so it needs the same right as a direct update.
    if data.progress and not has_permission(Role(actor.role), Permission.SCHEDULE_PROGRESS):
        raise ForbiddenError("Your role cannot update task progress.")
    if data.progress:
        ids = [entry.task_id for entry in data.progress]
        tasks = {t.id: t for t in db.scalars(select(Task).where(Task.id.in_(ids))).all()}
        if any(t.project_id != project.id for t in tasks.values()) or len(tasks) != len(ids):
            raise BusinessRuleError("Every task must belong to this project.")
    changed = []
    for entry in data.progress:
        task = tasks[entry.task_id]
        report.progress.append(
            ReportProgress(
                task_id=task.id,
                task_name=task.name,
                percent_before=task.percent_complete,
                percent_after=entry.percent_complete,
            )
        )
        if schedule_service.apply_progress(db, task, entry.percent_complete, on=data.report_date):
            changed.append(task.code or task.name)

    try:
        db.flush()
    except IntegrityError as exc:  # a parallel submit won the race for this date
        db.rollback()
        existing = _existing(db, project, data.report_date)
        raise _duplicate(existing) if existing else ConflictError() from exc
    if changed:
        schedule_service.record_snapshot(db, project)

    audit.record(
        db,
        AuditAction.REPORT_CREATED,
        meta=meta,
        actor_id=actor.id,
        target_type="daily_report",
        target_id=report.id,
        details={
            "project": project.code,
            "date": data.report_date.isoformat(),
            "tasks_updated": changed[:50],
        },
    )
    notification_service.send(
        db,
        [
            NewNotification(
                user_id=pm.id,
                kind="report_submitted",
                title=f"Daily report: {project.name}",
                body=f"{actor.full_name} filed the report for {data.report_date.strftime('%d %b')}"
                + (" and noted problems." if data.problems else "."),
                link=f"/reports/{report.id}",
                project_id=project.id,
                dedupe_key=f"report-submitted:{report.id}",
            )
            for pm in _site_managers(db, project, {Role.PROJECT_MANAGER})
        ],
    )
    db.commit()
    db.refresh(report)
    return report


def _require_author(report: DailyReport, user: User) -> None:
    if report.author_id != user.id:
        raise ForbiddenError("Only the engineer who wrote the report can change it.")
    if not is_editable(report, user):
        raise BusinessRuleError("Reports can only be changed on the day they were submitted.")


def update_report(
    db: Session, report: DailyReport, project: Project, data: ReportUpdate, *, actor: User, meta: RequestMeta
) -> DailyReport:
    _require_author(report, actor)
    changes = data.model_dump(exclude_unset=True)
    for required in ("crew_count", "work_done"):
        if required in changes and changes[required] is None:
            raise BusinessRuleError(f"{required.replace('_', ' ').capitalize()} cannot be empty.")
    if "weather_source" in changes and changes["weather_source"] is None:
        changes.pop("weather_source")
    for name, value in changes.items():
        setattr(report, name, value)
    audit.record(
        db,
        AuditAction.REPORT_UPDATED,
        meta=meta,
        actor_id=actor.id,
        target_type="daily_report",
        target_id=report.id,
        details={"project": project.code, "fields": sorted(changes)},
    )
    db.commit()
    db.refresh(report)
    return report


def add_photo(
    db: Session,
    report: DailyReport,
    project: Project,
    content: bytes,
    caption: str | None,
    *,
    actor: User,
    storage: Storage,
    max_photos: int,
    meta: RequestMeta,
) -> ReportPhoto:
    _require_author(report, actor)
    count = db.scalar(select(func.count(ReportPhoto.id)).where(ReportPhoto.report_id == report.id)) or 0
    if count >= max_photos:
        raise BusinessRuleError(f"A report can have at most {max_photos} photos.")
    processed = photos.process(content)
    stem = uuid.uuid4().hex
    key = f"{stem}.jpg"
    storage.save(key, processed.full)
    storage.save(f"{stem}_thumb.jpg", processed.thumb)
    position = (
        db.scalar(select(func.max(ReportPhoto.position)).where(ReportPhoto.report_id == report.id)) or 0
    ) + 1
    photo = ReportPhoto(
        report_id=report.id,
        uploaded_by=actor.id,
        storage_key=key,
        content_type="image/jpeg",
        size_bytes=len(processed.full),
        width=processed.width,
        height=processed.height,
        caption=caption,
        position=position,
        created_at=clock.utcnow(),
    )
    db.add(photo)
    audit.record(
        db,
        AuditAction.REPORT_PHOTO_ADDED,
        meta=meta,
        actor_id=actor.id,
        target_type="report_photo",
        target_id=photo.id,
        details={"project": project.code, "report": str(report.id)},
    )
    try:
        db.commit()
    except Exception:
        # Keep storage and database in step: no orphan files for a row that never landed.
        storage.delete(key)
        storage.delete(f"{stem}_thumb.jpg")
        raise
    return photo


def get_photo(db: Session, user: User, photo_id: uuid.UUID) -> tuple[ReportPhoto, DailyReport, Project]:
    photo = db.get(ReportPhoto, photo_id)
    if photo is None:
        raise NotFoundError("Photo not found.")
    try:
        report, project = get_report(db, user, photo.report_id)
    except NotFoundError as exc:
        raise NotFoundError("Photo not found.") from exc
    return photo, report, project


def thumb_key(photo: ReportPhoto) -> str:
    return photo.storage_key.replace(".jpg", "_thumb.jpg")


def delete_photo(
    db: Session,
    photo: ReportPhoto,
    report: DailyReport,
    project: Project,
    *,
    actor: User,
    storage: Storage,
    meta: RequestMeta,
) -> None:
    _require_author(report, actor)
    keys = (photo.storage_key, thumb_key(photo))
    db.delete(photo)
    audit.record(
        db,
        AuditAction.REPORT_PHOTO_DELETED,
        meta=meta,
        actor_id=actor.id,
        target_type="report_photo",
        target_id=photo.id,
        details={"project": project.code, "report": str(report.id)},
    )
    db.commit()
    for key in keys:  # after the commit: a failed delete leaves a file, never a broken row
        storage.delete(key)


def deadline_for(day: date, hour: int) -> datetime:
    return datetime.combine(day, time(hour=hour), tzinfo=clock.SITE_TIME_ZONE)


def today_status(db: Session, user: User, *, deadline_hour: int) -> ReportStatus:
    today = clock.site_today()
    stmt = scope_to_user_sites(
        select(Project).where(Project.status == ProjectStatus.ACTIVE.value).order_by(Project.name),
        Project.site_id,
        user,
    )
    projects = list(db.scalars(stmt).all())
    reports = {
        r.project_id: r
        for r in db.scalars(
            select(DailyReport).where(
                DailyReport.report_date == today, DailyReport.project_id.in_([p.id for p in projects])
            )
        ).all()
    }
    deadline = deadline_for(today, deadline_hour)
    return ReportStatus(
        date=today,
        deadline=deadline,
        deadline_passed=clock.utcnow() >= deadline,
        projects=[
            TodayStatus(
                project_id=p.id,
                project_code=p.code,
                project_name=p.name,
                site_code=p.site.code,
                report_id=reports[p.id].id if p.id in reports else None,
                submitted_at=reports[p.id].submitted_at if p.id in reports else None,
                author_name=reports[p.id].author.full_name if p.id in reports else None,
            )
            for p in projects
        ],
    )


def projects_missing_report(db: Session, day: date) -> list[Project]:
    """Active projects on active sites with no report for ``day`` (BR-07)."""
    has_report = exists().where(DailyReport.project_id == Project.id, DailyReport.report_date == day)
    return list(
        db.scalars(
            select(Project)
            .join(Site, Site.id == Project.site_id)
            .where(
                Project.status == ProjectStatus.ACTIVE.value,
                Site.is_active.is_(True),
                Project.start_date <= day,
                ~has_report,
            )
            .order_by(Project.code)
        ).all()
    )


def send_missing_report_reminders(db: Session, day: date) -> int:
    """Remind site engineers and project managers of every site still missing today's report.

    Idempotent: each person gets one reminder per project per day, however often this runs.
    """
    created = 0
    for project in projects_missing_report(db, day):
        items = []
        people = _site_managers(db, project, {Role.SITE_ENGINEER, Role.PROJECT_MANAGER})
        has_engineer = any(p.role == Role.SITE_ENGINEER.value for p in people)
        for person in people:
            engineer = person.role == Role.SITE_ENGINEER.value
            link = f"/projects/{project.id}/reports" + ("/new" if engineer else "")
            if engineer:
                action = " Please submit it now."
            elif has_engineer:
                action = " The site engineer has been reminded."
            else:
                action = " No site engineer is assigned to this site."
            items.append(
                NewNotification(
                    user_id=person.id,
                    kind="report_missing",
                    title=f"Daily report missing: {project.name}",
                    body=f"No daily report has been filed for {day.strftime('%d %b')} yet." + action,
                    link=link,
                    project_id=project.id,
                    dedupe_key=f"report-missing:{project.id}:{day.isoformat()}",
                )
            )
        created += notification_service.send(db, items)
    db.commit()
    return created
