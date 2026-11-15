import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import AppSettings, CurrentUser, DbSession, Meta, require_permission
from app.core.errors import ForbiddenError, NotFoundError
from app.core.permissions import Permission, Role, has_permission
from app.models import User
from app.schemas.schedule import (
    DependencyIn,
    DependencyOut,
    HolidayCountries,
    HolidayImportIn,
    HolidayImportOut,
    HolidayIn,
    HolidayList,
    HolidayOut,
    NetworkOut,
    ProgressOut,
    ScheduleSummary,
    ScheduleSummaryBasics,
    TaskCreate,
    TaskList,
    TaskOut,
    TaskUpdate,
)
from app.services import calendar_service, network_service, project_service, schedule_service
from app.services.visibility import shape_all

router = APIRouter(tags=["schedule"])

Reader = Annotated[User, Depends(require_permission(Permission.SCHEDULE_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.SCHEDULE_READ, Permission.SCHEDULE_MANAGE))]


def progress_editor(user: CurrentUser) -> User:
    """Managers edit tasks; site engineers may only report percent complete (checked in the service)."""
    role = Role(user.role)
    if not has_permission(role, Permission.SCHEDULE_READ) or not (
        has_permission(role, Permission.SCHEDULE_MANAGE) or has_permission(role, Permission.SCHEDULE_PROGRESS)
    ):
        raise ForbiddenError()
    return user


Editor = Annotated[User, Depends(progress_editor)]


@router.get("/schedule/summary", response_model=list[ScheduleSummary] | list[ScheduleSummaryBasics])
def schedule_summary(user: Reader, db: DbSession) -> list[ScheduleSummary] | list[ScheduleSummaryBasics]:
    return shape_all(user, schedule_service.summaries(db, user), ScheduleSummaryBasics)


@router.get("/projects/{project_id}/tasks", response_model=TaskList)
def list_tasks(project_id: uuid.UUID, user: Reader, db: DbSession) -> TaskList:
    return schedule_service.list_tasks(db, project_service.get_project(db, user, project_id))


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(project_id: uuid.UUID, body: TaskCreate, user: Manager, db: DbSession, meta: Meta) -> TaskOut:
    project = project_service.get_project(db, user, project_id)
    task = schedule_service.create_task(db, project, body, actor=user, meta=meta)
    return schedule_service.task_out(db, project, task)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, body: TaskUpdate, user: Editor, db: DbSession, meta: Meta) -> TaskOut:
    task, project = schedule_service.get_task(db, user, task_id)
    can_manage = has_permission(Role(user.role), Permission.SCHEDULE_MANAGE)
    task = schedule_service.update_task(db, task, project, body, can_manage=can_manage, actor=user, meta=meta)
    return schedule_service.task_out(db, project, task)


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: uuid.UUID, user: Manager, db: DbSession, meta: Meta) -> None:
    task, project = schedule_service.get_task(db, user, task_id)
    schedule_service.delete_task(db, task, project, actor=user, meta=meta)


@router.get("/projects/{project_id}/progress", response_model=ProgressOut)
def get_progress(project_id: uuid.UUID, user: Reader, db: DbSession) -> ProgressOut:
    return schedule_service.progress(db, project_service.get_project(db, user, project_id))


# --- Phase 9: the network (critical path and forecast), dependencies, holidays -------------------------


@router.get("/projects/{project_id}/network", response_model=NetworkOut)
def project_network(project_id: uuid.UUID, user: Reader, db: DbSession) -> NetworkOut:
    """The Gantt view: planned and forecast dates, the critical path, BR-06 and BR-11 flags."""
    return network_service.analyse(db, project_service.get_project(db, user, project_id))


@router.post(
    "/projects/{project_id}/dependencies", response_model=DependencyOut, status_code=status.HTTP_201_CREATED
)
def add_dependency(
    project_id: uuid.UUID, body: DependencyIn, user: Manager, db: DbSession, meta: Meta
) -> DependencyOut:
    project = project_service.get_project(db, user, project_id)
    return network_service.add_dependency(db, user, project, body, meta=meta)


@router.delete("/dependencies/{dependency_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_dependency(dependency_id: uuid.UUID, user: Manager, db: DbSession, meta: Meta) -> None:
    dep = network_service.get_dependency(db, dependency_id)
    try:
        project = project_service.get_project(db, user, dep.project_id)
    except NotFoundError as exc:  # out of scope looks exactly like missing
        raise NotFoundError("Dependency not found.") from exc
    network_service.remove_dependency(db, user, dep, project, meta=meta)


HolidayAdmin = Annotated[User, Depends(require_permission(Permission.HOLIDAYS_MANAGE))]


@router.get("/admin/holidays", response_model=HolidayList)
def list_holidays(_admin: HolidayAdmin, db: DbSession) -> HolidayList:
    return calendar_service.list_holidays(db)


@router.post("/admin/holidays", response_model=HolidayOut, status_code=status.HTTP_201_CREATED)
def add_holiday(body: HolidayIn, admin: HolidayAdmin, db: DbSession, meta: Meta) -> HolidayOut:
    return calendar_service.add_holiday(db, admin, body, meta=meta)


@router.get("/admin/holidays/countries", response_model=HolidayCountries)
def holiday_countries(_admin: HolidayAdmin, settings: AppSettings) -> HolidayCountries:
    return calendar_service.holiday_countries(settings.country)


@router.post("/admin/holidays/import", response_model=HolidayImportOut)
def import_holidays(
    body: HolidayImportIn, admin: HolidayAdmin, db: DbSession, meta: Meta
) -> HolidayImportOut:
    return calendar_service.import_holidays(db, admin, body, meta=meta)


@router.delete("/admin/holidays/{holiday_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_holiday(holiday_id: uuid.UUID, admin: HolidayAdmin, db: DbSession, meta: Meta) -> None:
    calendar_service.remove_holiday(db, admin, holiday_id, meta=meta)
