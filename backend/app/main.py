import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.database import Database
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.middleware import (
    BodySizeLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.rate_limit import RateLimiter
from app.core.scheduler import build_scheduler
from app.integrations.storage import LocalStorage
from app.integrations.weather import DisabledWeatherClient, OpenMeteoClient, WeatherClient

# Routes that accept file uploads get a larger body limit; everything else keeps the default.
UPLOAD_PATHS = re.compile(r"/api/v1/projects/[0-9a-fA-F-]{36}/boq/import")
PHOTO_PATHS = re.compile(r"/api/v1/reports/[0-9a-fA-F-]{36}/photos")
MULTIPART_OVERHEAD = 256 * 1024


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.environment != "development")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        scheduler = None
        if settings.scheduler_enabled:
            scheduler = build_scheduler(settings, app.state.database, app.state.weather_client)
            scheduler.start()
        yield
        if scheduler is not None:
            scheduler.shutdown(wait=False)
        app.state.database.dispose()

    app = FastAPI(
        lifespan=lifespan,
        title=settings.app_name,
        version=settings.version,
        debug=settings.debug,
        docs_url="/api/docs" if settings.docs_enabled else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.docs_enabled else None,
    )

    app.state.settings = settings
    app.state.database = Database(settings)
    app.state.rate_limiter = RateLimiter()
    app.state.storage = LocalStorage(settings.media_root)
    weather_client: WeatherClient = DisabledWeatherClient()
    if settings.weather_enabled:
        weather_client = OpenMeteoClient(settings.weather_timeout_seconds)
    app.state.weather_client = weather_client

    register_error_handlers(app)
    app.include_router(api_router)

    # Starlette runs the last-added middleware first, so this list reads inside -> outside.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    app.add_middleware(
        BodySizeLimitMiddleware,
        max_bytes=settings.max_request_body_bytes,
        overrides=[
            (UPLOAD_PATHS, settings.max_upload_body_bytes),
            (PHOTO_PATHS, settings.max_photo_bytes + MULTIPART_OVERHEAD),
        ],
    )
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.is_production)

    return app


app = create_app()
