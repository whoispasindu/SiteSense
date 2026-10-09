"""SQLAlchemy engine and session management.

Each app instance owns one ``Database`` built from its own ``Settings`` (stored on
``app.state``), so tests and tools can never silently talk to a database other than the one
they configured. ``create_engine`` does not connect until first use. Every connection gets a
server-side statement timeout so one runaway query cannot pin a worker.
"""

from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self.engine: Engine = create_engine(
            settings.database_url.get_secret_value(),
            pool_size=settings.db_pool_size,
            max_overflow=settings.db_pool_size,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={
                "connect_timeout": 5,
                "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
                "application_name": "sitesense-api",
            },
        )
        self.session_factory = sessionmaker(bind=self.engine, autoflush=False, expire_on_commit=False)

    def dispose(self) -> None:
        self.engine.dispose()


def get_db(request: Request) -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed, rolled back on error."""
    database: Database = request.app.state.database
    session = database.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def ping_database(session: Session) -> None:
    session.execute(text("SELECT 1"))
