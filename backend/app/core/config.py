"""Application settings, loaded from environment variables (and a local .env file in development).

Secrets are typed as ``SecretStr`` so they never appear in logs or reprs. Unsafe combinations
(for example debug mode or wildcard CORS in production) are rejected at startup rather than
silently accepted.
"""

from functools import lru_cache
from typing import Annotated, Literal

from fastapi import Request
from pydantic import Field, PostgresDsn, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["development", "test", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="SITESENSE_",
        extra="ignore",
    )

    app_name: str = "SiteSense API"
    version: str = "0.1.0"
    environment: Environment = "development"
    debug: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # Runtime connection uses the least-privilege application role (DML only).
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://sitesense_app:change-me-app@127.0.0.1:5432/sitesense"
    )
    # Migrations run as the schema owner. Falls back to database_url when unset.
    migration_database_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=50)
    # BR-12: a task with this many working days of float or fewer counts as near-critical (Phase 10).
    br12_float_days: int = Field(default=5, ge=0, le=60)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100, le=300_000)

    # NoDecode: read comma-separated strings from env instead of requiring JSON.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:5173"]
    allowed_hosts: Annotated[list[str], NoDecode] = ["localhost", "127.0.0.1", "backend", "testserver"]

    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)
    # File upload routes only (BOQ import): the 5 MB file plus multipart overhead.
    max_upload_body_bytes: int = Field(default=6 * 1_048_576, ge=1024)

    # --- Authentication -------------------------------------------------------------------
    # HS256 signing key for access tokens. Generate one with:
    #   python -c "import secrets; print(secrets.token_urlsafe(48))"
    jwt_secret: SecretStr = SecretStr("dev-only-insecure-jwt-secret-change-me-0000000000")
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=60)
    refresh_token_ttl_days: int = Field(default=7, ge=1, le=30)
    # A refresh-token family (one sign-in) can be rotated for at most this long.
    session_max_days: int = Field(default=30, ge=1, le=90)
    # Refresh cookie is Secure by default; browsers accept Secure cookies on http://localhost.
    cookie_secure: bool = True
    login_max_failures: int = Field(default=5, ge=3, le=20)
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    # Per-client-IP request budgets for the auth endpoints (per minute).
    login_rate_per_minute: int = Field(default=10, ge=1)
    refresh_rate_per_minute: int = Field(default=30, ge=1)
    # BOQ imports parse spreadsheets (CPU-heavy): a small per-IP budget.
    boq_import_rate_per_minute: int = Field(default=20, ge=1)

    # --- Site reports (Phase 4) -------------------------------------------------------------
    # Where photo files live (local folder). Never inside a web-served directory.
    media_root: str = "var/media"
    max_photo_bytes: int = Field(default=10 * 1_048_576, ge=1024, le=50 * 1_048_576)
    max_photos_per_report: int = Field(default=12, ge=1, le=50)
    # Photo decoding is CPU-heavy: a per-IP budget.
    photo_upload_rate_per_minute: int = Field(default=60, ge=1)
    # Analysing a report runs the text classifier (up to 0.4 s of CPU): a per-IP budget.
    analyze_rate_per_minute: int = Field(default=30, ge=1)
    # Open-Meteo forecast (free, no key). Off: the app uses cached forecasts only.
    weather_enabled: bool = True
    weather_cache_hours: int = Field(default=3, ge=1, le=48)
    weather_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    # In-process scheduler for reminders and weather refresh. Off in tests and one-off tools.
    scheduler_enabled: bool = True
    # BR-07: every active site submits its daily report by this hour (site time).
    report_deadline_hour: int = Field(default=18, ge=0, le=23)

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("jwt_secret")
    @classmethod
    def _validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("jwt_secret must be at least 32 characters")
        return value

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _validate_dsn(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            PostgresDsn(value.get_secret_value())
        return value

    @model_validator(mode="after")
    def _reject_unsafe_production_config(self) -> "Settings":
        if self.environment != "production":
            return self
        problems: list[str] = []
        if self.debug:
            problems.append("debug must be off")
        if "*" in self.cors_origins or "*" in self.allowed_hosts:
            problems.append("wildcard CORS origins / allowed hosts are not permitted")
        if any(origin.startswith("http://") for origin in self.cors_origins):
            problems.append("CORS origins must use https")
        for name in ("database_url", "migration_database_url"):
            url = getattr(self, name)
            if url is not None and "change-me" in url.get_secret_value():
                problems.append(f"{name} still uses the example password")
        secret = self.jwt_secret.get_secret_value()
        if "change-me" in secret or "insecure" in secret:
            problems.append("jwt_secret is the development default")
        if not self.cookie_secure:
            problems.append("cookie_secure must be on")
        if problems:
            raise ValueError("Unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def docs_enabled(self) -> bool:
        return not self.is_production

    @property
    def effective_migration_url(self) -> str:
        url = self.migration_database_url or self.database_url
        return url.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    """Settings from the environment. Used once at startup and by Alembic."""
    return Settings()


def app_settings(request: Request) -> Settings:
    """FastAPI dependency: the settings this app instance was created with."""
    settings: Settings = request.app.state.settings
    return settings
