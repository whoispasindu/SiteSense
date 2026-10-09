"""Programme tasks and progress. Access always goes through the task's project (site scoping)."""

import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, ForbiddenError, NotFoundError
from app.models import BoqSection, ProgressSnapshot, Project, Task, User
from app.schemas.project import MAX_PROJECT_DAYS
from app.schemas.schedule import (
    CurvePointOut,
    ProgressOut,
    ScheduleSummary,
    TaskCreate,
    TaskList,
    TaskOut,
    TaskState,
    TaskUpdate,
)
from app.services import audit, project_service
from app.services.audit import AuditAction, RequestMeta
from app.services.progress import TaskPlan, actual_percent, planned_fraction, planned_percent, progress_curve

MAX_TASKS_PER_PROJECT = 500
CENTI = Decimal("0.01")
# Behind by more than this many percentage points (task or project) counts as "behind".
BEHIND_TOLERANCE = 5.0


def _plan(task: Task) -> TaskPlan:
    return TaskPlan(task.planned_start, task.planned_end, task.weight, task.percent_complete)


def _tasks(db: Session, project: Project) -> list[Task]:
    return list(
        db.scalars(select(Task).where(Task.project_id == project.id).order_by(Task.position, Task.id)).all()
    )


def _state(task: Task, planned_today: float) -> TaskState:
    done = float(task.percent_complete)
    if done >= 100:
        return "done"
    if planned_today <= 0 and done == 0:
        return "not_started"
    return "behind" if done + BEHIND_TOLERANCE < planned_today else "on_track"


def to_task_out(task: Task, section_codes: dict[uuid.UUID, str]) -> TaskOut:
    planned_today = round(planned_fraction(_plan(task), clock.site_today()) * 100, 1)
    return TaskOut(
        id=task.id,
        project_id=task.project_id,
        code=task.code,
        name=task.name,
        boq_section_id=task.boq_section_id,
        boq_section_code=section_codes.get(task.boq_section_id) if task.boq_section_id else None,
        planned_start=task.planned_start,
        planned_end=task.planned_end,
        # Always two places, whether the value was just set in Python or read back from NUMERIC(5,2).
        weight=task.weight.quantize(CENTI),
        percent_complete=task.percent_complete.quantize(CENTI),
        is_critical=task.is_critical,
        position=task.position,
        planned_percent_today=planned_today,
        state=_state(task, planned_today),
        progress_updated_at=task.progress_updated_at,
    )


def section_codes(db: Session, project: Project) -> dict[uuid.UUID, str]:
    rows = db.execute(select(BoqSection.id, BoqSection.code).where(BoqSection.project_id == project.id)).all()
    return {row.id: row.code for row in rows}


def list_tasks(db: Session, project: Project) -> TaskList:
    tasks = _tasks(db, project)
    codes = section_codes(db, project)
    return TaskList(
        tasks=[to_task_out(t, codes) for t in tasks],
        weight_total=sum((t.weight for t in tasks), Decimal(0)).quantize(CENTI),
    )


def get_task(db: Session, user: User, task_id: uuid.UUID) -> tuple[Task, Project]:
    task = db.get(Task, task_id)
    if task is None:
        raise NotFoundError("Task not found.")
    try:
        project = project_service.get_project(db, user, task.project_id)
    except NotFoundError as exc:  # same answer whether the task is missing or out of scope
        raise NotFoundError("Task not found.") from exc
    return task, project


def record_snapshot(db: Session, project: Project) -> None:
    """Upsert today's actual progress. Called after every change that can move it."""
    value = Decimal(str(actual_percent([_plan(t) for t in _tasks(db, project)])))
    stmt = insert(ProgressSnapshot).values(
        id=uuid.uuid4(), project_id=project.id, snapshot_date=clock.site_today(), actual_percent=value
    )
    db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_progress_snapshots_project_date",
            set_={"actual_percent": stmt.excluded.actual_percent},
        )
    )


def _check_section(db: Session, project: Project, section_id: uuid.UUID | None) -> None:
    if section_id is None:
        return
    owner = db.scalar(select(BoqSection.project_id).where(BoqSection.id == section_id))
    if owner != project.id:
        raise BusinessRuleError("The BOQ section must belong to this project.")


def _check_dates(project: Project, task: Task) -> None:
    if task.planned_end < task.planned_start:
        raise BusinessRuleError("The planned end must be on or after the planned start.")
    if task.planned_start < project.start_date:
        raise BusinessRuleError("A task cannot start before the project starts.")
    if (task.planned_end - project.start_date).days > MAX_PROJECT_DAYS:
        raise BusinessRuleError("A task cannot end more than 15 years after the project starts.")


def create_task(db: Session, project: Project, data: TaskCreate, *, actor: User, meta: RequestMeta) -> Task:
    count = db.scalar(select(func.count(Task.id)).where(Task.project_id == project.id)) or 0
    if count >= MAX_TASKS_PER_PROJECT:
        raise BusinessRuleError(f"A project can have at most {MAX_TASKS_PER_PROJECT} tasks.")
    _check_section(db, project, data.boq_section_id)
    position = (db.scalar(select(func.max(Task.position)).where(Task.project_id == project.id)) or 0) + 1
    task = Task(project_id=project.id, position=position, **data.model_dump())
    if task.percent_complete > 0:
        task.progress_updated_at = clock.utcnow()
    _check_dates(project, task)
    db.add(task)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Another task in this project already uses that code.") from exc
    record_snapshot(db, project)
    audit.record(
        db,
        AuditAction.TASK_CREATED,
        meta=meta,
        actor_id=actor.id,
        target_type="task",
        target_id=task.id,
        details={"project": project.code, "name": task.name, "weight": str(task.weight)},
    )
    db.commit()
    return task


def update_task(
    db: Session,
    task: Task,
    project: Project,
    data: TaskUpdate,
    *,
    can_manage: bool,
    actor: User,
    meta: RequestMeta,
) -> Task:
    changes = data.model_dump(exclude_unset=True)
    if not can_manage and set(changes) - {"percent_complete"}:
        raise ForbiddenError("You can update a task's percent complete only.")
    for required in ("name", "planned_start", "planned_end", "weight", "percent_complete", "is_critical"):
        if required in changes and changes[required] is None:
            raise BusinessRuleError(f"{required.replace('_', ' ').capitalize()} cannot be empty.")
    if "boq_section_id" in changes:
        _check_section(db, project, changes["boq_section_id"])

    before = task.percent_complete
    changed = {k: v for k, v in changes.items() if getattr(task, k) != v}
    for key, value in changed.items():
        setattr(task, key, value)
    if not changed:
        return task
    _check_dates(project, task)
    if "percent_complete" in changed:
        task.progress_updated_at = clock.utcnow()
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Another task in this project already uses that code.") from exc

    record_snapshot(db, project)
    if set(changed) == {"percent_complete"}:
        action = AuditAction.TASK_PROGRESS_UPDATED
        details: dict[str, object] = {
            "from": str(before.quantize(CENTI)),
            "to": str(task.percent_complete.quantize(CENTI)),
        }
    else:
        action = AuditAction.TASK_UPDATED
        details = {"fields": sorted(changed)}
    audit.record(
        db, action, meta=meta, actor_id=actor.id, target_type="task", target_id=task.id, details=details
    )
    db.commit()
    return task


def delete_task(db: Session, task: Task, project: Project, *, actor: User, meta: RequestMeta) -> None:
    name = task.name
    db.delete(task)
    db.flush()
    record_snapshot(db, project)
    audit.record(
        db,
        AuditAction.TASK_DELETED,
        meta=meta,
        actor_id=actor.id,
        target_type="task",
        target_id=task.id,
        details={"project": project.code, "name": name},
    )
    db.commit()


def progress(db: Session, project: Project) -> ProgressOut:
    tasks = _tasks(db, project)
    plans = [_plan(t) for t in tasks]
    today = clock.site_today()
    start = min([project.start_date, *(t.planned_start for t in tasks)])
    end = max([project.planned_end, *(t.planned_end for t in tasks)])
    snapshots = [
        (row.snapshot_date, float(row.actual_percent))
        for row in db.scalars(select(ProgressSnapshot).where(ProgressSnapshot.project_id == project.id)).all()
    ]
    points = progress_curve(plans, start=start, end=end, today=today, snapshots=snapshots)
    planned_now = planned_percent(plans, today)
    actual_now = actual_percent(plans)
    return ProgressOut(
        as_of=today,
        planned_percent=planned_now,
        actual_percent=actual_now,
        variance=round(actual_now - planned_now, 2),
        weight_total=sum((t.weight for t in tasks), Decimal(0)).quantize(CENTI),
        task_count=len(tasks),
        programme_start=start,
        programme_end=end,
        contract_end=project.planned_end,
        points=[CurvePointOut(date=p.on, planned=p.planned, actual=p.actual) for p in points],
    )


def summaries(db: Session, user: User) -> list[ScheduleSummary]:
    """Planned against actual for every project the user can see (the Schedule page)."""
    today = clock.site_today()
    projects = project_service.list_projects(db, user)
    if not projects:
        return []
    by_project: dict[uuid.UUID, list[TaskPlan]] = {}
    for task in db.scalars(select(Task).where(Task.project_id.in_([p.id for p in projects]))).all():
        by_project.setdefault(task.project_id, []).append(_plan(task))
    out = []
    for summary in projects:
        plans = by_project.get(summary.id, [])
        planned_now, actual_now = planned_percent(plans, today), actual_percent(plans)
        out.append(
            ScheduleSummary(
                project=summary,
                planned_percent=planned_now,
                actual_percent=actual_now,
                variance=round(actual_now - planned_now, 2),
                task_count=len(plans),
            )
        )
    return out
