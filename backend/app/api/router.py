from fastapi import APIRouter

from app.api.v1 import admin, auth, health, materials, notifications, projects, reports, schedule, sites

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(sites.router)
api_router.include_router(projects.router)
api_router.include_router(schedule.router)
api_router.include_router(reports.router)
api_router.include_router(materials.router)
api_router.include_router(notifications.router)
api_router.include_router(admin.router)
