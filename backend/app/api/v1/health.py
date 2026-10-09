from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.config import Settings, app_settings
from app.core.database import get_db, ping_database
from app.core.logging import get_logger
from app.schemas.health import HealthResponse, ReadinessResponse

router = APIRouter(prefix="/health", tags=["health"])
log = get_logger(__name__)


@router.get("", response_model=HealthResponse, summary="Liveness: the process is up")
def liveness(settings: Annotated[Settings, Depends(app_settings)]) -> HealthResponse:
    return HealthResponse(status="ok", version=settings.version)


@router.get(
    "/ready",
    response_model=ReadinessResponse,
    summary="Readiness: dependencies are reachable",
    responses={503: {"model": ReadinessResponse}},
)
def readiness(response: Response, db: Annotated[Session, Depends(get_db)]) -> ReadinessResponse:
    try:
        ping_database(db)
    except SQLAlchemyError:
        # The cause goes to the log only; callers learn nothing about the database setup.
        log.warning("readiness_check_failed", check="database", exc_info=True)
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return ReadinessResponse(status="degraded", checks={"database": "unavailable"})
    return ReadinessResponse(status="ok", checks={"database": "ok"})
