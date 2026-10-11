"""The programme network (Phase 9): dependencies, critical path, forecast, BR-06 and BR-11.

- **Planned network:** each task's planned dates as durations in working days, linked by its
  dependencies; its end is the plan's own end.
- **Forecast network:** what is done keeps its actual dates; work under way finishes at its own rate
  so far (``app.rules.schedule.remaining_days``); work not begun starts no earlier than its planned
  start or today, and after its predecessors. Its critical path shows which delays move the handover
  date. Nothing is stored: the network is calculated from the tasks on each request.
- **BR-11:** an open stop-work flag stops the tasks it names, or the whole project. Stopped tasks take
  no progress (``schedule_service.apply_progress``). Their stopped days do not count as work, so
  each stopped working day moves their forecast one working day later, and the forecast critical
  path, slip and (through the progress gap) the risk model see it.
- **BR-06:** a concrete pour whose forecast window has a working day with 10 mm or more of rain
  forecast is flagged, and the site's project managers are alerted (once per task and set of days).
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import clock
from app.core.errors import BusinessRuleError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Role
from app.models import (
    ActionKind,
    ActionStatus,
    Project,
    ProjectStatus,
    ReportAction,
    ReportActionTask,
    Task,
    TaskDependency,
    User,
    WeatherForecast,
)
from app.rules import schedule as rules
from app.rules.calendar import MAX_SEARCH_DAYS, CalendarError, WorkCalendar
from app.schemas.schedule import DependencyIn, DependencyOut, NetworkOut, StopWorkOut, TaskTimingOut
from app.services import audit, calendar_service, notification_service
from app.services.audit import AuditAction, RequestMeta
from app.services.notification_service import NewNotification

HORIZON = timedelta(days=MAX_SEARCH_DAYS - 1)  # every count from the project start fits

log = get_logger(__name__)
CHECKED_STATUSES = (ProjectStatus.ACTIVE.value, ProjectStatus.ON_HOLD.value)
MAX_DAYS_NAMED = 5  # a pour alert names at most this many rain days
MAX_LINKS_PER_PROJECT = 2000  # four per task at the 500-task limit


def _site_date(moment: object) -> date:
    return moment.astimezone(clock.SITE_TIME_ZONE).date()  # type: ignore[attr-defined, no-any-return]


# --- BR-11: what stop-work flags stop ------------------------------------------------------------------


def stop_work_actions(db: Session, project_id: uuid.UUID, *, open_only: bool) -> list[ReportAction]:
    stmt = select(ReportAction).where(
        ReportAction.project_id == project_id, ReportAction.kind == ActionKind.STOP_WORK.value
    )
    if open_only:
        stmt = stmt.where(ReportAction.status == ActionStatus.OPEN.value)
    return list(db.scalars(stmt.order_by(ReportAction.created_at)).all())


def action_task_ids(db: Session, action_ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, set[uuid.UUID]]:
    ids = list(action_ids)
    out: dict[uuid.UUID, set[uuid.UUID]] = {i: set() for i in ids}
    if ids:
        for action_id, task_id in db.execute(
            select(ReportActionTask.action_id, ReportActionTask.task_id).where(
                ReportActionTask.action_id.in_(ids)
            )
        ).all():
            out[action_id].add(task_id)
    return out


def stopped(db: Session, project_id: uuid.UUID) -> tuple[bool, set[uuid.UUID]]:
    """(whole project stopped, ids of stopped tasks) from the project's open stop-work flags."""
    actions = stop_work_actions(db, project_id, open_only=True)
    whole = any(a.stop_scope == "project" for a in actions)
    tasks = set().union(*action_task_ids(db, [a.id for a in actions if a.stop_scope == "tasks"]).values())
    return whole, tasks


def is_stopped(db: Session, task: Task) -> bool:
    whole, tasks = stopped(db, task.project_id)
    return whole or task.id in tasks


def stopped_days(
    db: Session, project: Project, tasks: list[Task], calendar: WorkCalendar, today: date
) -> dict[uuid.UUID, int]:
    """Working days each task has been stopped since it started (open and cleared flags), up to today."""
    actions = stop_work_actions(db, project.id, open_only=False)
    listed = action_task_ids(db, [a.id for a in actions if a.stop_scope == "tasks"])
    out: dict[uuid.UUID, int] = {}
    for task in tasks:
        if task.actual_start is None:
            out[task.id] = 0
            continue
        spans: list[tuple[date, date]] = []
        for action in actions:
            if action.stop_scope == "tasks" and task.id not in listed.get(action.id, set()):
                continue
            first = max(_site_date(action.created_at), task.actual_start)
            last = today if action.closed_at is None else _site_date(action.closed_at) - timedelta(days=1)
            if task.actual_finish is not None:
                last = min(last, task.actual_finish)
            if first <= last:
                spans.append((first, last))
        out[task.id] = sum(calendar.count(first, last) for first, last in _merged(spans))
    return out


def _merged(spans: list[tuple[date, date]]) -> list[tuple[date, date]]:
    """Overlapping or touching date ranges joined, so a day stopped by two flags counts once."""
    merged: list[tuple[date, date]] = []
    for first, last in sorted(spans):
        if merged and first <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], last))
        else:
            merged.append((first, last))
    return merged


# --- The network ---------------------------------------------------------------------------------------


def _tasks(db: Session, project_id: uuid.UUID) -> list[Task]:
    return list(
        db.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.position, Task.id)).all()
    )


def _dependencies(db: Session, project_id: uuid.UUID) -> list[TaskDependency]:
    return list(db.scalars(select(TaskDependency).where(TaskDependency.project_id == project_id)).all())


def _rain(db: Session, project: Project, today: date) -> dict[date, Decimal | None]:
    rows = db.execute(
        select(WeatherForecast.forecast_date, WeatherForecast.rain_mm).where(
            WeatherForecast.site_id == project.site_id, WeatherForecast.forecast_date >= today
        )
    ).all()
    return {row.forecast_date: row.rain_mm for row in rows}


def _forecast_activities(
    tasks: list[Task],
    planned_duration: dict[uuid.UUID, int],
    calendar: WorkCalendar,
    today: date,
    stopped_now: set[uuid.UUID],
    days_stopped: dict[uuid.UUID, int],
) -> list[rules.Activity]:
    """Done work keeps its dates; work under way finishes at its own rate; the rest starts from today."""
    next_day = calendar.on_or_after(today + timedelta(days=1))
    activities = []
    for t in tasks:
        if t.actual_finish is not None:
            activities.append(
                rules.Activity(
                    t.id,
                    planned_duration[t.id],
                    t.planned_start,
                    fixed_start=t.actual_start,
                    fixed_finish=t.actual_finish,
                )
            )
        elif t.actual_start is not None:
            active = max(calendar.count(t.actual_start, today) - days_stopped[t.id], 0)
            left = rules.remaining_days(
                percent_complete=t.percent_complete,
                active_days=active,
                planned_duration=planned_duration[t.id],
            )
            activities.append(
                rules.Activity(
                    t.id,
                    planned_duration[t.id],
                    t.planned_start,
                    fixed_start=t.actual_start,
                    fixed_finish=calendar.finish(next_day, left),
                )
            )
        else:
            earliest = max(t.planned_start, next_day if t.id in stopped_now else today)
            activities.append(rules.Activity(t.id, planned_duration[t.id], earliest))
    return activities


def analyse(db: Session, project: Project, today: date | None = None) -> NetworkOut:
    today = today or clock.site_today()
    tasks = _tasks(db, project.id)
    deps = _dependencies(db, project.id)
    calendar = calendar_service.calendar_for(db, project)
    links = [rules.Link(d.predecessor_id, d.successor_id, d.lag_days) for d in deps]
    whole, stopped_ids = stopped(db, project.id)
    stopped_now = {t.id for t in tasks if whole or t.id in stopped_ids}
    days_stopped = stopped_days(db, project, tasks, calendar, today)

    planned_duration = {t.id: max(calendar.count(t.planned_start, t.planned_end), 1) for t in tasks}
    beyond_horizon = False
    try:
        planned = rules.analyse(
            [rules.Activity(t.id, planned_duration[t.id], t.planned_start) for t in tasks], links, calendar
        )
        forecast = rules.analyse(
            _forecast_activities(tasks, planned_duration, calendar, today, stopped_now, days_stopped),
            links,
            calendar,
        )
        if max(planned.finish or today, forecast.finish or today) - project.start_date >= HORIZON:
            raise CalendarError("The network ends past the calendar's horizon.")  # slip could not be counted
    except CalendarError:
        # Long lags or very slow work push the network past the calendar's 30-year horizon. Show each
        # task on its own dates, with no critical path, and say why, so the PM can still fix it.
        beyond_horizon = True
        planned = forecast = rules.analyse(
            [
                rules.Activity(
                    t.id,
                    planned_duration[t.id],
                    t.planned_start,
                    fixed_start=t.actual_start or t.planned_start,
                    fixed_finish=t.actual_finish or t.planned_end,
                )
                for t in tasks
            ],
            [],
            calendar,
        )

    rain = _rain(db, project, today)
    preds: dict[uuid.UUID, list[uuid.UUID]] = {t.id: [] for t in tasks}
    for d in deps:
        preds[d.successor_id].append(d.predecessor_id)
    timings = []
    for t in tasks:
        f = forecast.timings[t.id]
        done = t.actual_finish is not None
        timings.append(
            TaskTimingOut(
                task_id=t.id,
                code=t.code,
                name=t.name,
                percent_complete=t.percent_complete,
                planned_start=t.planned_start,
                planned_end=t.planned_end,
                planned_duration=planned_duration[t.id],
                forecast_start=f.early_start,
                forecast_finish=f.early_finish,
                slip_days=calendar.gap(t.planned_end, f.early_finish),
                total_float=f.total_float,
                is_critical=f.critical and not done and not beyond_horizon,
                is_done=done,
                stopped=t.id in stopped_now,
                stopped_days=days_stopped[t.id],
                is_concrete_pour=t.is_concrete_pour,
                rain_days=[]
                if done or not t.is_concrete_pour
                else rules.pour_rain_days(max(f.early_start, today), f.early_finish, rain, calendar),
                predecessors=preds[t.id],
            )
        )

    forecast_end = forecast.finish
    last = max([d for d in (forecast_end, project.planned_end, planned.finish) if d is not None])
    first = min([project.start_date, *(t.planned_start for t in tasks)])
    warnings = [
        f"No holidays are entered for {year}: its Poya days and public holidays count as working days. "
        "The Company Admin can add them."
        for year in calendar_service.missing_years(db, first, last)
    ]
    if beyond_horizon:
        warnings.insert(
            0,
            "The forecast runs more than 30 years out, so tasks are shown on their own dates with no "
            "critical path. Check for very long lags, and the progress of the slowest tasks.",
        )
    actions = stop_work_actions(db, project.id, open_only=True)
    listed = action_task_ids(db, [a.id for a in actions])
    return NetworkOut(
        project_id=project.id,
        as_of=today,
        working_week=project.working_week,
        planned_end=project.planned_end,
        network_end=planned.finish,
        forecast_end=forecast_end,
        slip_days=calendar.gap(project.planned_end, forecast_end) if forecast_end else 0,
        tasks=timings,
        dependencies=[
            DependencyOut(
                id=d.id, predecessor_id=d.predecessor_id, successor_id=d.successor_id, lag_days=d.lag_days
            )
            for d in deps
        ],
        stop_work=[
            StopWorkOut(
                action_id=a.id,
                report_id=a.report_id,
                summary=a.summary,
                scope=a.stop_scope or "project",
                task_ids=sorted(listed.get(a.id, set())),
                since=a.created_at,
            )
            for a in actions
        ],
        warnings=warnings,
    )


def critical_task_ids(db: Session, project: Project) -> set[uuid.UUID]:
    return {t.task_id for t in analyse(db, project).tasks if t.is_critical}


# --- Dependencies --------------------------------------------------------------------------------------


def add_dependency(
    db: Session, user: User, project: Project, data: DependencyIn, *, meta: RequestMeta
) -> DependencyOut:
    tasks = {
        t.id: t for t in db.scalars(select(Task).where(Task.id.in_([data.predecessor_id, data.successor_id])))
    }
    if len(tasks) != 2 or any(t.project_id != project.id for t in tasks.values()):
        raise BusinessRuleError("Both tasks must be in this project's programme.")
    # Serialise changes to the project's network, so two links added at once cannot close a loop.
    db.execute(select(Project.id).where(Project.id == project.id).with_for_update())
    existing = [rules.Link(d.predecessor_id, d.successor_id) for d in _dependencies(db, project.id)]
    if len(existing) >= MAX_LINKS_PER_PROJECT:
        raise BusinessRuleError(f"A programme can have at most {MAX_LINKS_PER_PROJECT} links.")
    if rules.creates_cycle(existing, data.predecessor_id, data.successor_id):
        error = BusinessRuleError("That would make a loop: the second task already leads back to the first.")
        error.code = "dependency_loop"
        raise error
    dep = TaskDependency(
        project_id=project.id,
        predecessor_id=data.predecessor_id,
        successor_id=data.successor_id,
        lag_days=data.lag_days,
        created_by=user.id,
        created_at=clock.utcnow(),
    )
    db.add(dep)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Those tasks are already linked.") from exc
    audit.record(
        db,
        AuditAction.DEPENDENCY_ADDED,
        meta=meta,
        actor_id=user.id,
        target_type="task",
        target_id=data.successor_id,
        details={
            "project": project.code,
            "after": tasks[data.predecessor_id].code or tasks[data.predecessor_id].name,
            "task": tasks[data.successor_id].code or tasks[data.successor_id].name,
            "lag_days": data.lag_days,
        },
    )
    db.commit()
    return DependencyOut(
        id=dep.id, predecessor_id=dep.predecessor_id, successor_id=dep.successor_id, lag_days=dep.lag_days
    )


def get_dependency(db: Session, dependency_id: uuid.UUID) -> TaskDependency:
    dep = db.get(TaskDependency, dependency_id)
    if dep is None:
        raise NotFoundError("Dependency not found.")
    return dep


def remove_dependency(
    db: Session, user: User, dep: TaskDependency, project: Project, *, meta: RequestMeta
) -> None:
    details = {"project": project.code, "predecessor": str(dep.predecessor_id)}
    successor = dep.successor_id
    db.delete(dep)
    audit.record(
        db,
        AuditAction.DEPENDENCY_REMOVED,
        meta=meta,
        actor_id=user.id,
        target_type="task",
        target_id=successor,
        details=details,
    )
    db.commit()


# --- BR-06: concrete pours on heavy-rain days ---------------------------------------------------------


def check_pours(db: Session, project: Project, today: date | None = None) -> int:
    """Alert the site's PMs about pours with heavy rain forecast in their window. Returns the alerts sent.

    One notification per task and set of rain days: the same forecast does not alert twice, a new
    heavy-rain day does. The caller commits.
    """
    if project.status not in CHECKED_STATUSES:
        return 0
    flagged = [t for t in analyse(db, project, today).tasks if t.rain_days]
    if not flagged:
        return 0
    pms = notification_service.site_people(db, project.site_id, {Role.PROJECT_MANAGER})
    items: list[NewNotification] = []
    for t in flagged:
        named = ", ".join(d.strftime("%d %b") for d in t.rain_days[:MAX_DAYS_NAMED])
        more = len(t.rain_days) - MAX_DAYS_NAMED
        days = named + (f" and {more} more day{'s' if more > 1 else ''}" if more > 0 else "")
        label = f"{t.code + ' ' if t.code else ''}{t.name[:120]}"
        # The key names the set of rain days (hashed: a long forecast must not outgrow the column).
        fingerprint = hashlib.sha256("|".join(d.isoformat() for d in t.rain_days).encode()).hexdigest()[:24]
        items.extend(
            NewNotification(
                user_id=pm.id,
                kind="pour_rain",
                title=f"Heavy rain forecast for a pour on {project.code}",
                body=f"{label}: 10 mm or more forecast on {days} (BR-06).",
                link=f"/projects/{project.id}/schedule",
                project_id=project.id,
                dedupe_key=f"pour-rain:{t.task_id}:{fingerprint}",
            )
            for pm in pms
        )
    return notification_service.send(db, items)


def check_pours_after_change(db: Session, project: Project) -> None:
    """Best effort after a pour task or its dates change; never undoes the change."""
    try:
        check_pours(db, project)
        db.commit()
    except Exception:
        db.rollback()
        log.exception("pour_check_failed", project=project.code)


def check_all_pours(db: Session) -> int:
    sent = 0
    for project in db.scalars(
        select(Project).where(Project.status.in_(CHECKED_STATUSES)).order_by(Project.code)
    ).all():
        try:
            sent += check_pours(db, project)
            db.commit()
        except Exception:
            db.rollback()
            log.exception("pour_check_failed", project=project.code)
    log.info("pours_checked", alerts=sent)
    return sent
