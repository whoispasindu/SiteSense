import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.deps import DbSession, Meta, rate_limit, require_permission
from app.core.errors import BusinessRuleError, PayloadTooLargeError
from app.core.permissions import Permission
from app.models import ProjectStatus, User
from app.schemas.project import (
    BoqOut,
    BudgetLineUpdate,
    ImportReport,
    ProjectCreate,
    ProjectDetail,
    ProjectSummary,
    ProjectUpdate,
    SectionTotals,
)
from app.services import project_service
from app.services.boq_import import MAX_FILE_BYTES, BoqFileError, parse_boq

router = APIRouter(prefix="/projects", tags=["projects"])

Reader = Annotated[User, Depends(require_permission(Permission.PROJECTS_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.PROJECTS_MANAGE))]
BoqManager = Annotated[User, Depends(require_permission(Permission.PROJECTS_READ, Permission.BOQ_MANAGE))]

ALLOWED_UPLOAD_SUFFIXES = (".xlsx", ".csv")


@router.get("", response_model=list[ProjectSummary])
def list_projects(
    user: Reader,
    db: DbSession,
    status: ProjectStatus | None = None,
    q: Annotated[str | None, Query(max_length=80)] = None,
) -> list[ProjectSummary]:
    return project_service.list_projects(db, user, status=status, query=q)


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
def create_project(body: ProjectCreate, user: Manager, db: DbSession, meta: Meta) -> ProjectDetail:
    project = project_service.create_project(db, body, actor=user, meta=meta)
    return project_service.project_detail(db, project)


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: uuid.UUID, user: Reader, db: DbSession) -> ProjectDetail:
    return project_service.project_detail(db, project_service.get_project(db, user, project_id))


@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: uuid.UUID, body: ProjectUpdate, user: Manager, db: DbSession, meta: Meta
) -> ProjectDetail:
    project = project_service.get_project(db, user, project_id)
    project = project_service.update_project(db, project, body, actor=user, meta=meta)
    return project_service.project_detail(db, project)


@router.get("/{project_id}/boq", response_model=BoqOut)
def get_boq(project_id: uuid.UUID, user: Reader, db: DbSession) -> BoqOut:
    return project_service.get_boq(db, project_service.get_project(db, user, project_id))


@router.post(
    "/{project_id}/boq/import",
    response_model=ImportReport,
    dependencies=[Depends(rate_limit("boq-import", "boq_import_rate_per_minute"))],
)
def import_boq(
    project_id: uuid.UUID,
    user: BoqManager,
    db: DbSession,
    meta: Meta,
    file: Annotated[UploadFile, File(description="BOQ as .xlsx or .csv, at most 5 MB")],
    dry_run: bool = True,
) -> ImportReport:
    """Validate (``dry_run=true``, the default) or validate and replace the project's BOQ."""
    project = project_service.get_project(db, user, project_id)
    file_name = (file.filename or "boq").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if not file_name.lower().endswith(ALLOWED_UPLOAD_SUFFIXES):
        raise BusinessRuleError("Upload the BOQ as an .xlsx or .csv file.")
    content = file.file.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise PayloadTooLargeError("The file is larger than 5 MB.")
    try:
        parsed = parse_boq(file_name, content)
    except BoqFileError as exc:
        raise BusinessRuleError(str(exc)) from exc
    return project_service.import_boq(
        db, project, parsed, file_name=file_name, dry_run=dry_run, actor=user, meta=meta
    )


@router.patch("/{project_id}/budget-lines/{line_id}", response_model=SectionTotals)
def update_budget_line(
    project_id: uuid.UUID,
    line_id: uuid.UUID,
    body: BudgetLineUpdate,
    user: BoqManager,
    db: DbSession,
    meta: Meta,
) -> SectionTotals:
    project = project_service.get_project(db, user, project_id)
    line = project_service.update_budget_line(db, project, line_id, body.budget_amount, actor=user, meta=meta)
    totals = {s.budget_line_id: s for s in project_service.project_detail(db, project).sections}
    return totals[line.id]
