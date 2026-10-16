import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile, status
from fastapi.responses import Response

from app.api.deps import AppSettings, DbSession, Meta, rate_limit, require_permission
from app.core.errors import NotFoundError, PayloadTooLargeError
from app.core.logging import get_logger
from app.core.permissions import Permission
from app.integrations.storage import Storage
from app.integrations.weather import WeatherClient
from app.models import User
from app.schemas.report import (
    PhotoOut,
    ReportCreate,
    ReportDetail,
    ReportList,
    ReportStatus,
    ReportUpdate,
    WeatherDayOut,
    WeatherOut,
)
from app.services import project_service, report_service, risk_service, weather

router = APIRouter(tags=["reports"])
log = get_logger(__name__)

Reader = Annotated[User, Depends(require_permission(Permission.REPORTS_READ))]
Author = Annotated[User, Depends(require_permission(Permission.REPORTS_READ, Permission.REPORTS_CREATE))]
ProjectReader = Annotated[User, Depends(require_permission(Permission.PROJECTS_READ))]

HEAVY_RAIN_MM = Decimal("10.0")  # BR-06 threshold, shown on the weather strip


def _storage(request: Request) -> Storage:
    storage: Storage = request.app.state.storage
    return storage


def _weather_client(request: Request) -> WeatherClient:
    client: WeatherClient = request.app.state.weather_client
    return client


PhotoStorage = Annotated[Storage, Depends(_storage)]


@router.get("/reports/today", response_model=ReportStatus)
def today_status(user: Reader, db: DbSession, settings: AppSettings) -> ReportStatus:
    """Today's report status for every active project the user can see (BR-07)."""
    return report_service.today_status(db, user, deadline_hour=settings.report_deadline_hour)


@router.get("/projects/{project_id}/reports", response_model=ReportList)
def list_reports(
    project_id: uuid.UUID,
    user: Reader,
    db: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 30,
    offset: Annotated[int, Query(ge=0, le=100_000)] = 0,
) -> ReportList:
    project = project_service.get_project(db, user, project_id)
    return report_service.list_reports(db, project, limit=limit, offset=offset)


@router.post(
    "/projects/{project_id}/reports", response_model=ReportDetail, status_code=status.HTTP_201_CREATED
)
def create_report(
    project_id: uuid.UUID, body: ReportCreate, user: Author, db: DbSession, meta: Meta, settings: AppSettings
) -> ReportDetail:
    project = project_service.get_project(db, user, project_id)
    report = report_service.create_report(db, project, body, actor=user, meta=meta)
    # A new report changes the crew, progress and reporting inputs: re-score (best effort).
    risk_service.rescore_after_report(db, project)
    return report_service.to_detail(report, project, user, settings.max_photos_per_report)


@router.get("/reports/{report_id}", response_model=ReportDetail)
def get_report(report_id: uuid.UUID, user: Reader, db: DbSession, settings: AppSettings) -> ReportDetail:
    report, project = report_service.get_report(db, user, report_id)
    return report_service.to_detail(report, project, user, settings.max_photos_per_report)


@router.patch("/reports/{report_id}", response_model=ReportDetail)
def update_report(
    report_id: uuid.UUID, body: ReportUpdate, user: Author, db: DbSession, meta: Meta, settings: AppSettings
) -> ReportDetail:
    report, project = report_service.get_report(db, user, report_id)
    report = report_service.update_report(db, report, project, body, actor=user, meta=meta)
    return report_service.to_detail(report, project, user, settings.max_photos_per_report)


@router.post(
    "/reports/{report_id}/photos",
    response_model=PhotoOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("photo-upload", "photo_upload_rate_per_minute", per_user=True))],
)
def upload_photo(
    report_id: uuid.UUID,
    user: Author,
    db: DbSession,
    meta: Meta,
    settings: AppSettings,
    storage: PhotoStorage,
    file: Annotated[UploadFile, File(description="JPEG, PNG or WebP photo")],
    caption: Annotated[str | None, Form(max_length=200)] = None,
) -> PhotoOut:
    report, project = report_service.get_report(db, user, report_id)
    content = file.file.read(settings.max_photo_bytes + 1)
    if len(content) > settings.max_photo_bytes:
        raise PayloadTooLargeError(f"Photos can be at most {settings.max_photo_bytes // 1_048_576} MB.")
    photo = report_service.add_photo(
        db,
        report,
        project,
        content,
        (caption or "").strip() or None,
        actor=user,
        storage=storage,
        max_photos=settings.max_photos_per_report,
        meta=meta,
    )
    return PhotoOut(
        id=photo.id,
        caption=photo.caption,
        width=photo.width,
        height=photo.height,
        size_bytes=photo.size_bytes,
        created_at=photo.created_at,
    )


@router.get("/photos/{photo_id}", response_class=Response)
def get_photo(
    photo_id: uuid.UUID,
    user: Reader,
    db: DbSession,
    storage: PhotoStorage,
    size: Literal["full", "thumb"] = "full",
) -> Response:
    """The photo bytes, for signed-in users who can see the report. Never a public URL."""
    photo, _, _ = report_service.get_photo(db, user, photo_id)
    key = photo.storage_key if size == "full" else report_service.thumb_key(photo)
    try:
        content = storage.read(key)
    except OSError as exc:
        log.error("photo_file_missing", photo_id=str(photo.id))
        raise NotFoundError("The photo file is missing.") from exc
    return Response(
        content=content,
        media_type="image/jpeg",
        headers={
            # Private: browsers may keep it briefly, shared caches never.
            "Cache-Control": "private, max-age=600",
            "Content-Disposition": f'inline; filename="site-photo-{photo.id.hex[:8]}.jpg"',
        },
    )


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(photo_id: uuid.UUID, user: Author, db: DbSession, meta: Meta, storage: PhotoStorage) -> None:
    photo, report, project = report_service.get_photo(db, user, photo_id)
    report_service.delete_photo(db, photo, report, project, actor=user, storage=storage, meta=meta)


@router.get("/projects/{project_id}/weather", response_model=WeatherOut)
def project_weather(
    project_id: uuid.UUID,
    user: ProjectReader,
    db: DbSession,
    settings: AppSettings,
    client: Annotated[WeatherClient, Depends(_weather_client)],
) -> WeatherOut:
    project = project_service.get_project(db, user, project_id)
    result = weather.forecast(db, project.site, client, cache_hours=settings.weather_cache_hours)
    return WeatherOut(
        site_code=project.site.code,
        available=result.available,
        stale=result.stale,
        fetched_at=result.fetched_at,
        message=result.message,
        days=[
            WeatherDayOut(
                date=d.forecast_date,
                summary=d.summary,
                weather_code=d.weather_code,
                temp_max_c=d.temp_max_c,
                temp_min_c=d.temp_min_c,
                rain_mm=d.rain_mm,
                rain_probability=d.rain_probability,
            )
            for d in result.days
        ],
        heavy_rain_threshold_mm=HEAVY_RAIN_MM,
    )
