from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, read from environment variables or a .env file."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "SiteSense API"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://sitesense:sitesense@localhost:5432/sitesense"
    cors_origins: list[str] = ["http://localhost:5173"]


settings = Settings()
