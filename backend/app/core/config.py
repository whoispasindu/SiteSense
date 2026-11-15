"""Application settings, loaded from environment variables (and a local .env file in development).

Secrets are typed as ``SecretStr`` so they never appear in logs or reprs. Unsafe combinations
(for example debug mode or wildcard CORS in production) are rejected at startup rather than
silently accepted.
"""

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
        # An empty variable means "not set" (Compose passes optional settings as empty strings).
        env_ignore_empty=True,
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
    # Two-step sign-in (Phase 13): encrypts the authenticator secrets at rest and keys the recovery
    # codes. 32+ characters; changing it invalidates every enrolment. Generate like jwt_secret.
    mfa_key: SecretStr = SecretStr("dev-only-insecure-mfa-key-change-me-000000000000000")
    # How long the step between password and code may take.
    mfa_challenge_minutes: int = Field(default=5, ge=1, le=15)
    mfa_rate_per_minute: int = Field(default=10, ge=1, le=100)
    # Whether roles in MFA_ROLES must set up two-step sign-in. Always on in production (checked below);
    # the test suite turns it off by default and its two-step tests turn it back on.
    mfa_enforced: bool = True
    # Demo mode: the seeded demo accounts skip two-step enforcement so anyone can sign in, and a
    # "Demo data" banner shows. Never for a real company.
    demo_mode: bool = False
    login_max_failures: int = Field(default=5, ge=3, le=20)
    lockout_minutes: int = Field(default=15, ge=1, le=1440)
    # Per-client-IP request budgets for the auth endpoints (per minute).
    login_rate_per_minute: int = Field(default=10, ge=1)
    refresh_rate_per_minute: int = Field(default=30, ge=1)
    # BOQ imports parse spreadsheets (CPU-heavy): a small per-user budget.
    boq_import_rate_per_minute: int = Field(default=20, ge=1)

    # --- Site reports (Phase 4) -------------------------------------------------------------
    # Where photo files live (local folder). Never inside a web-served directory.
    media_root: str = "var/media"
    max_photo_bytes: int = Field(default=10 * 1_048_576, ge=1024, le=50 * 1_048_576)
    max_photos_per_report: int = Field(default=12, ge=1, le=50)
    # Photo decoding is CPU-heavy: a per-user budget.
    photo_upload_rate_per_minute: int = Field(default=60, ge=1)
    # Analysing a report runs the text classifier (up to 0.4 s of CPU): a per-user budget.
    analyze_rate_per_minute: int = Field(default=30, ge=1)
    # Phase 13: every write (POST, PUT, PATCH, DELETE) shares one budget per signed-in user (per IP
    # before sign-in), and the heavy reads and runs (what-if, weekly PDF) have a smaller one.
    write_rate_per_minute: int = Field(default=120, ge=1)
    heavy_rate_per_minute: int = Field(default=20, ge=1)
    # Open-Meteo forecast (free, no key). Off: the app uses cached forecasts only.
    weather_enabled: bool = True
    weather_cache_hours: int = Field(default=3, ge=1, le=48)
    weather_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    # In-process scheduler for reminders and weather refresh. Off in tests and one-off tools.
    scheduler_enabled: bool = True
    # BR-07: every active site submits its daily report by this hour (site time).
    report_deadline_hour: int = Field(default=18, ge=0, le=23)
    # Daily briefing (Phase 11). Optional: with no key, everyone gets the rule-based briefing. Only
    # structured facts are sent (app/ai/briefing), never report text or people's names.
    anthropic_api_key: SecretStr | None = None
    briefing_model: str = Field(default="claude-haiku-5-5", pattern=r"^[a-z0-9][a-z0-9.\-]{2,63}$")
    briefing_timeout_seconds: float = Field(default=20.0, gt=0, le=120)
    # Email (Phase 11). With no SMTP host, emails are written to the log instead of sent.
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_security: Literal["starttls", "ssl", "none"] = "starttls"
    email_from: str = "SiteSense <no-reply@sitesense.example>"
    # Links in emails open the web app here.
    app_base_url: str = "http://localhost:5173"
    # The evening digest of non-urgent alerts (site time).
    digest_hour: int = Field(default=18, ge=0, le=23)
    digest_minute: int = Field(default=30, ge=0, le=59)

    # --- The company's country, time zone and currency ----------------------------------------
    # Set once when SiteSense is installed (the setup script asks). "Today" on site, every scheduled
    # job and the weather follow the time zone; changing it needs a restart of the API and scheduler.
    time_zone: str = "Asia/Colombo"
    # ISO 3166 country code: the default for importing public holidays.
    country: str = Field(default="LK", pattern=r"^[A-Z]{2}$")
    # ISO 4217 currency code. Amounts are never converted: set it before the first project.
    currency: str = Field(default="LKR", pattern=r"^[A-Z]{3}$")
    # How numbers are written (a BCP 47 locale such as en-GB or de-DE).
    number_locale: str = Field(default="en-LK", pattern=r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
    # The risk model was trained on contract values in Sri Lankan rupees: how many LKR one unit of
    # the currency is worth, for the model's contract-size input only. Required unless LKR.
    risk_lkr_per_unit: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000"))
    # The rain history fetched once per site outside Sri Lanka (Open-Meteo archive, about 14 years).
    climate_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    @field_validator("cors_origins", "allowed_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("jwt_secret", "mfa_key")
    @classmethod
    def _validate_jwt_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("secrets must be at least 32 characters")
        return value

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def _validate_dsn(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None:
            PostgresDsn(value.get_secret_value())
        return value

    @field_validator("time_zone")
    @classmethod
    def _validate_time_zone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown time zone {value!r} (use an IANA name such as Europe/London)") from exc
        return value

    @model_validator(mode="after")
    def _check_risk_rate(self) -> "Settings":
        if self.currency == "LKR":
            if self.risk_lkr_per_unit not in (None, Decimal(1)):
                raise ValueError("risk_lkr_per_unit must be 1 (or unset) when the currency is LKR")
        elif self.risk_lkr_per_unit is None:
            raise ValueError(
                f"set SITESENSE_RISK_LKR_PER_UNIT: how many Sri Lankan rupees one {self.currency} is worth "
                "(the risk model was trained on contract values in LKR)"
            )
        return self

    @property
    def lkr_per_unit(self) -> Decimal:
        return self.risk_lkr_per_unit or Decimal(1)

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
        mfa_key = self.mfa_key.get_secret_value()
        if "change-me" in mfa_key or "insecure" in mfa_key:
            problems.append("mfa_key is the development default")
        if mfa_key == secret:
            problems.append("mfa_key must differ from jwt_secret")
        if not self.mfa_enforced:
            problems.append("two-step sign-in must be enforced (mfa_enforced)")
        if not self.cookie_secure:
            problems.append("cookie_secure must be on")
        if not self.app_base_url.startswith("https://"):
            problems.append("app_base_url must use https (links in emails)")
        if self.smtp_host and self.smtp_security == "none":
            problems.append("SMTP must use TLS (starttls or ssl)")
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
