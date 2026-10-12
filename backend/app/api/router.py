from fastapi import APIRouter

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

api_router = APIRouter(prefix="/api/v1")
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
