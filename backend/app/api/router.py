from fastapi import APIRouter, Depends

from app.api.deps import limit_writes
from app.api.v1 import (
    admin,
    auth,
    contract,
    dashboard,
    health,
    issues,
    materials,
    notifications,
    portal,
    projects,
    reports,
    risk,
    schedule,
    sites,
)

# Every write shares a per-user budget (Phase 13); some routes add a tighter one of their own.
api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(limit_writes)])
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sites.router)
api_router.include_router(projects.router)
api_router.include_router(schedule.router)
# Before reports: /reports/weekly.pdf must not be read as /reports/{report_id}.
api_router.include_router(dashboard.router)
api_router.include_router(reports.router)
api_router.include_router(issues.router)
api_router.include_router(materials.router)
api_router.include_router(contract.router)
api_router.include_router(risk.router)
api_router.include_router(notifications.router)
api_router.include_router(portal.router)
api_router.include_router(admin.router)
