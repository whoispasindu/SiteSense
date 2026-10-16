"""The demo's nightly reset (Phase 13): back to the seeded data, whatever visitors did during the day.

Only with ``SITESENSE_DEMO_MODE`` on, and only on a database that holds the seeded demo accounts:
it deletes every row except the reference data the migrations load (roles, and the holidays no
one added by hand), and every stored photo file. The caller seeds the demo again afterwards.

It runs as the schema owner (``SITESENSE_MIGRATION_DATABASE_URL``): the runtime role may never
delete audit rows, and that stays true. Rows are deleted child-first, so the reference data the
migrations loaded survives (a TRUNCATE ... CASCADE through users would also empty the holidays).
"""

from dataclasses import dataclass

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.logging import get_logger
from app.integrations.storage import Storage
from app.models import Holiday, ReportPhoto, User
from app.models.base import Base

log = get_logger(__name__)

# Loaded by the migrations, not by the seed: kept.
KEPT_TABLES = frozenset({"alembic_version", "roles", "holidays"})


class DemoResetRefusedError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ResetResult:
    rows: int
    photo_files: int


def _thumb_key(key: str) -> str:
    stem, _, ext = key.rpartition(".")
    return f"{stem}_thumb.{ext}"


def reset(db: Session, settings: Settings, storage: Storage) -> ResetResult:
    """Delete everything the demo seed (and the demo's visitors) created. Commits."""
    if not settings.demo_mode:
        raise DemoResetRefusedError("The demo reset only runs with SITESENSE_DEMO_MODE on.")
    if db.scalar(select(User.id).where(User.is_demo.is_(True)).limit(1)) is None:
        raise DemoResetRefusedError("No seeded demo accounts here: this does not look like a demo database.")

    photo_keys = list(db.scalars(select(ReportPhoto.storage_key)))
    rows = 0
    # Holidays a visitor added go; the ones the migrations loaded (no author) stay.
    rows += db.execute(delete(Holiday).where(Holiday.created_by.is_not(None))).rowcount or 0  # type: ignore[attr-defined]
    for table in reversed(Base.metadata.sorted_tables):
        if table.name not in KEPT_TABLES:
            rows += db.execute(table.delete()).rowcount or 0  # type: ignore[attr-defined]
    db.commit()

    removed = 0
    for key in photo_keys:
        for name in (key, _thumb_key(key)):
            try:
                storage.delete(name)
                removed += 1
            except (OSError, ValueError):
                log.warning("demo_reset_photo_not_removed", key=name)
    log.info("demo_reset", rows=rows, photo_files=removed)
    return ResetResult(rows=rows, photo_files=removed)


def reset_as_owner(settings: Settings, storage: Storage) -> ResetResult:
    """The reset on its own short-lived owner connection (the CLI and the nightly job)."""
    if not settings.demo_mode:
        raise DemoResetRefusedError("The demo reset only runs with SITESENSE_DEMO_MODE on.")
    engine = create_engine(
        settings.effective_migration_url, connect_args={"application_name": "sitesense-demo-reset"}
    )
    try:
        with Session(bind=engine, expire_on_commit=False) as db:
            return reset(db, settings, storage)
    finally:
        engine.dispose()
