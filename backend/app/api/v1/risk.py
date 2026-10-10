"""Risk forecasts (Phase 6): the project's latest score with its drivers, and the dashboard ranking.

Project managers and quantity surveyors only (``risk:read``), on their own sites. Scores are
written by the scheduler, after daily reports and by the CLI, never by these endpoints.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.models import User
from app.schemas.risk import ProjectRisk, RiskRanking
from app.services import risk_service

router = APIRouter(tags=["risk"])

RiskReader = Annotated[User, Depends(require_permission(Permission.RISK_READ))]


@router.get("/projects/{project_id}/risk", response_model=ProjectRisk)
def project_risk(project_id: uuid.UUID, user: RiskReader, db: DbSession) -> ProjectRisk:
    return risk_service.project_risk(db, user, project_id)


@router.get("/risk/projects", response_model=list[RiskRanking])
def risk_ranking(user: RiskReader, db: DbSession) -> list[RiskRanking]:
    """Projects on the user's sites, highest risk first."""
    return risk_service.ranking(db, user)
