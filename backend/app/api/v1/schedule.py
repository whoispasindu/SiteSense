import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, Meta, require_permission
from app.core.errors import ForbiddenError
from app.core.permissions import Permission, Role, has_permission
from app.models import User
from app.schemas.schedule import ProgressOut, ScheduleSummary, TaskCreate, TaskList, TaskOut, TaskUpdate
from app.services import project_service, schedule_service

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


@router.get("/schedule/summary", response_model=list[ScheduleSummary])
def schedule_summary(user: Reader, db: DbSession) -> list[ScheduleSummary]:
    return schedule_service.summaries(db, user)


@router.get("/projects/{project_id}/tasks", response_model=TaskList)
def list_tasks(project_id: uuid.UUID, user: Reader, db: DbSession) -> TaskList:
    return schedule_service.list_tasks(db, project_service.get_project(db, user, project_id))


@router.post("/projects/{project_id}/tasks", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(project_id: uuid.UUID, body: TaskCreate, user: Manager, db: DbSession, meta: Meta) -> TaskOut:
    project = project_service.get_project(db, user, project_id)
    task = schedule_service.create_task(db, project, body, actor=user, meta=meta)
    return schedule_service.to_task_out(task, schedule_service.section_codes(db, project))


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: uuid.UUID, body: TaskUpdate, user: Editor, db: DbSession, meta: Meta) -> TaskOut:
    task, project = schedule_service.get_task(db, user, task_id)
    can_manage = has_permission(Role(user.role), Permission.SCHEDULE_MANAGE)
    task = schedule_service.update_task(db, task, project, body, can_manage=can_manage, actor=user, meta=meta)
    return schedule_service.to_task_out(task, schedule_service.section_codes(db, project))


@router.delete("/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: uuid.UUID, user: Manager, db: DbSession, meta: Meta) -> None:
    task, project = schedule_service.get_task(db, user, task_id)
    schedule_service.delete_task(db, task, project, actor=user, meta=meta)


@router.get("/projects/{project_id}/progress", response_model=ProgressOut)
def get_progress(project_id: uuid.UUID, user: Reader, db: DbSession) -> ProgressOut:
    return schedule_service.progress(db, project_service.get_project(db, user, project_id))
