import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings
from app.main import create_app
from tests.conftest import make_settings

SAFE_PROD = {
    "environment": "production",
    "cors_origins": ["https://app.sitesense.example"],
    "allowed_hosts": ["api.sitesense.example"],
    "database_url": "postgresql+psycopg://app:s3cure-pw@db:5432/sitesense",
    "app_base_url": "https://app.sitesense.example",
    "mfa_key": "a-real-production-mfa-key-value-0123456789abcdef",
    "mfa_enforced": True,
}


def test_safe_production_settings_are_accepted() -> None:
    settings = make_settings(**SAFE_PROD)

    assert settings.is_production
    assert not settings.docs_enabled


@pytest.mark.parametrize(
    ("override", "problem"),
    [
        ({"debug": True}, "debug must be off"),
        ({"cors_origins": ["*"]}, "wildcard"),
        ({"allowed_hosts": ["*"]}, "wildcard"),
        ({"cors_origins": ["http://app.sitesense.example"]}, "https"),
        ({"database_url": "postgresql+psycopg://app:change-me-app@db/sitesense"}, "database_url still"),
        (
            {"migration_database_url": "postgresql+psycopg://owner:change-me-owner@db/sitesense"},
            "migration_database_url still",
        ),
        ({"app_base_url": "http://app.sitesense.example"}, "app_base_url must use https"),
        ({"smtp_host": "mail.example", "smtp_security": "none"}, "SMTP must use TLS"),
        (
            {"mfa_key": "dev-only-insecure-mfa-key-change-me-000000000000000"},
            "mfa_key is the development default",
        ),
        ({"mfa_enforced": False}, "two-step sign-in must be enforced"),
    ],
)
def test_unsafe_production_settings_are_rejected(override: dict[str, object], problem: str) -> None:
    with pytest.raises(ValidationError, match=problem):
        make_settings(**{**SAFE_PROD, **override})


def test_database_url_must_be_postgres() -> None:
    with pytest.raises(ValidationError):
        make_settings(database_url="mysql://root@localhost/db")


def test_secrets_are_hidden_in_repr() -> None:
    settings = make_settings(database_url="postgresql+psycopg://app:top-secret-pw@db:5432/sitesense")

    assert "top-secret-pw" not in repr(settings)
    assert "top-secret-pw" not in str(settings.model_dump())


def test_comma_separated_lists_are_read_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SITESENSE_CORS_ORIGINS", "http://localhost:5173, http://127.0.0.1:5173")
    monkeypatch.setenv("SITESENSE_ALLOWED_HOSTS", "localhost,backend")

    settings = Settings(_env_file=None)

    assert settings.cors_origins == ["http://localhost:5173", "http://127.0.0.1:5173"]
    assert settings.allowed_hosts == ["localhost", "backend"]


def test_migration_url_falls_back_to_runtime_url() -> None:
    runtime = "postgresql+psycopg://app:pw@db:5432/sitesense"
    owner = "postgresql+psycopg://owner:pw@db:5432/sitesense"

    assert make_settings(database_url=runtime).effective_migration_url == runtime
    assert make_settings(database_url=runtime, migration_database_url=owner).effective_migration_url == owner


def test_api_docs_are_disabled_in_production() -> None:
    with TestClient(create_app(make_settings(**SAFE_PROD))) as client:
        assert client.get("/api/openapi.json", headers={"Host": "api.sitesense.example"}).status_code == 404
        assert client.get("/api/docs", headers={"Host": "api.sitesense.example"}).status_code == 404


def test_api_docs_are_available_outside_production(client: TestClient) -> None:
    assert client.get("/api/openapi.json").status_code == 200
