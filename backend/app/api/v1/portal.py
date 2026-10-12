"""The client portal (Phase 12), and the project manager's side of it.

Clients (``client:portal``) read their own projects: progress, the published handover date,
milestones, shared photos and approved claims. Each response is a client-only schema. Variation
decisions stay in ``contract.py`` (``POST /variations/{id}/client-decision``, Phase 8).

Project managers (``projects:manage``) publish or confirm the handover date and share photos;
schedule readers see the handover state and report readers the project's photos.
"""

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response

from app.api.deps import DbSession, Meta, require_permission
from app.api.v1.reports import PhotoStorage
from app.core.errors import NotFoundError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.models import User
from app.schemas.portal import (
    ClientClaims,
    ClientProject,
    ClientProjectCard,
    HandoverIn,
    HandoverState,
    PhotosShareIn,
    ProjectPhotos,
)
from app.services import handover_service, photos, portal_service, project_service, report_service

log = get_logger(__name__)
router = APIRouter(tags=["client portal"])

Client = Annotated[User, Depends(require_permission(Permission.CLIENT_PORTAL))]
ScheduleReader = Annotated[User, Depends(require_permission(Permission.SCHEDULE_READ))]
ReportReader = Annotated[User, Depends(require_permission(Permission.REPORTS_READ))]
Manager = Annotated[User, Depends(require_permission(Permission.PROJECTS_MANAGE))]


# --- The client ----------------------------------------------------------------------------------------


@router.get("/client/projects", response_model=list[ClientProjectCard])
def client_projects(user: Client, db: DbSession) -> list[ClientProjectCard]:
    return portal_service.list_projects(db, user)


@router.get("/client/projects/{project_id}", response_model=ClientProject)
def client_project(project_id: uuid.UUID, user: Client, db: DbSession) -> ClientProject:
    """Progress, the handover date and its reason, milestones and shared photos. No internal costs."""
    return portal_service.project_view(db, user, project_id)


@router.get("/client/projects/{project_id}/claims", response_model=ClientClaims)
def client_claims(project_id: uuid.UUID, user: Client, db: DbSession) -> ClientClaims:
    """Approved and paid progress claims, the contract value and the retention held so far."""
    return portal_service.claims_view(db, user, project_id)


@router.get("/client/photos/{photo_id}", response_class=Response)
def client_photo(
    photo_id: uuid.UUID,
    user: Client,
    db: DbSession,
    storage: PhotoStorage,
    size: Literal["full", "thumb"] = "full",
) -> Response:
    """A photo the project manager shared, with no metadata (no GPS, device or timestamps)."""
    photo = portal_service.shared_photo(db, user, photo_id)
    key = photo.storage_key if size == "full" else report_service.thumb_key(photo)
    try:
        content = photos.without_metadata(storage.read(key))
    except OSError as exc:
        log.error("photo_file_missing", photo_id=str(photo.id))
        raise NotFoundError("The photo file is missing.") from exc
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "private, max-age=600",
            "Content-Disposition": f'inline; filename="site-photo-{photo.id.hex[:8]}.jpg"',
        },
    )


# --- The project manager -------------------------------------------------------------------------------


@router.get("/projects/{project_id}/handover", response_model=HandoverState)
def handover(project_id: uuid.UUID, user: ScheduleReader, db: DbSession) -> HandoverState:
    """The published handover date, its history, suggestions, and whether it looks out of date."""
    project = project_service.get_project(db, user, project_id)
    return handover_service.state(db, user, project)


@router.post("/projects/{project_id}/handover", response_model=HandoverState)
def publish_handover(
    project_id: uuid.UUID, data: HandoverIn, user: Manager, db: DbSession, meta: Meta
) -> HandoverState:
    """Publish the date the client sees, with a reason for them. Audited; the clients are told."""
    project = project_service.get_project(db, user, project_id)
    handover_service.publish(db, user, project, data, meta=meta)
    return handover_service.state(db, user, project)


@router.post("/projects/{project_id}/handover/confirm", response_model=HandoverState)
def confirm_handover(project_id: uuid.UUID, user: Manager, db: DbSession, meta: Meta) -> HandoverState:
    """The published date was reviewed and stands. Audited; resets the 30-day reminder."""
    project = project_service.get_project(db, user, project_id)
    handover_service.confirm(db, user, project, meta=meta)
    return handover_service.state(db, user, project)


@router.get("/projects/{project_id}/photos", response_model=ProjectPhotos)
def project_photos(
    project_id: uuid.UUID,
    user: ReportReader,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=portal_service.PHOTO_LIMIT)] = portal_service.PHOTO_LIMIT,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ProjectPhotos:
    """Every photo in the project's reports, newest first, with whether the client can see it."""
    project = project_service.get_project(db, user, project_id)
    return portal_service.project_photos(db, project, limit=limit, offset=offset)


@router.post("/projects/{project_id}/photos/client-share", response_model=ProjectPhotos)
def share_photos(
    project_id: uuid.UUID, data: PhotosShareIn, user: Manager, db: DbSession, meta: Meta
) -> ProjectPhotos:
    """Share or unshare one or more of the project's photos with its clients. Audited."""
    project = project_service.get_project(db, user, project_id)
    return portal_service.set_shared(db, user, project, data, meta=meta)
