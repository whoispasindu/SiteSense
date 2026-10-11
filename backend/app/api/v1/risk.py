"""Risk forecasts (Phase 6): the project's latest score with its drivers, and the dashboard ranking.
The what-if planner (Phase 10) tests recovery actions on today's forecast.

Project managers and quantity surveyors read risk (``risk:read``); only project managers use the
planner (``risk:what_if``). Always on their own sites. Scores are written by the scheduler, after
daily reports and by the CLI, never by these endpoints; the planner stores nothing.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_permission
from app.core.permissions import Permission
from app.models import User
from app.schemas.risk import ProjectRisk, RiskRanking, WhatIfIn, WhatIfOut
from app.services import risk_service

router = APIRouter(tags=["risk"])

RiskReader = Annotated[User, Depends(require_permission(Permission.RISK_READ))]
WhatIfUser = Annotated[User, Depends(require_permission(Permission.RISK_WHAT_IF))]


@router.get("/projects/{project_id}/risk", response_model=ProjectRisk)
def project_risk(project_id: uuid.UUID, user: RiskReader, db: DbSession) -> ProjectRisk:
    return risk_service.project_risk(db, user, project_id)


@router.get("/risk/projects", response_model=list[RiskRanking])
def risk_ranking(user: RiskReader, db: DbSession) -> list[RiskRanking]:
    """Projects on the user's sites, highest risk first."""
    return risk_service.ranking(db, user)


@router.post("/projects/{project_id}/risk/what-if", response_model=WhatIfOut)
def what_if(project_id: uuid.UUID, data: WhatIfIn, user: WhatIfUser, db: DbSession) -> WhatIfOut:
    """Today's forecast, each recovery action's effect, and the chosen actions together. Stores nothing."""
    return risk_service.what_if(db, user, project_id, data)
