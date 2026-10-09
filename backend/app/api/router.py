from fastapi import APIRouter

from app.api import health

# Every feature router is registered here, e.g. api_router.include_router(projects.router)
api_router = APIRouter()
api_router.include_router(health.router)
