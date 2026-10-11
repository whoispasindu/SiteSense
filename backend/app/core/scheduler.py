"""Scheduled jobs (APScheduler, in-process).

- 18:00 site time: remind sites that have not filed today's report (BR-07).
- 05:30 site time: refresh the weather forecast for every active site.
- 06:00 site time: re-score every open project's risk (Phase 6), after the weather is fresh.

Jobs are safe to run more than once (several API workers, a restart, the CLI): reminders are
de-duplicated in the database and weather refresh is an upsert. Each job opens its own session
and never lets an exception escape into the scheduler thread.
"""

from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.integrations.weather import WeatherClient, WeatherUnavailableError
from app.models import Site
from app.services import cost_service, network_service, report_service, risk_service, weather

log = get_logger(__name__)


def run_report_reminders(session_factory: Callable[[], Session]) -> int:
    with session_factory() as db:
        created = report_service.send_missing_report_reminders(db, clock.site_today())
    log.info("report_reminders_sent", created=created)
    return created


def refresh_weather(session_factory: Callable[[], Session], client: WeatherClient) -> int:
    refreshed = 0
    with session_factory() as db:
        located = (Site.is_active.is_(True), Site.latitude.is_not(None), Site.longitude.is_not(None))
        sites = db.scalars(select(Site).where(*located)).all()
        for site in sites:
            try:
                weather.refresh(db, site, client)
                refreshed += 1
            except WeatherUnavailableError as exc:
                db.rollback()
                log.warning("weather_refresh_failed", site=site.code, reason=str(exc)[:200])
    log.info("weather_refreshed", sites=refreshed)
    return refreshed


def run_risk_scoring(session_factory: Callable[[], Session]) -> int:
    with session_factory() as db:
        scored = risk_service.score_all(db)
    return len(scored)


def run_pour_check(session_factory: Callable[[], Session]) -> int:
    with session_factory() as db:
        return network_service.check_all_pours(db)


def run_variance_check(session_factory: Callable[[], Session]) -> int:
    with session_factory() as db:
        return cost_service.check_all(db)


def _guarded(name: str, job: Callable[[], object]) -> Callable[[], None]:
    def run() -> None:
        try:
            job()
        except Exception:
            log.exception("scheduled_job_failed", job=name)

    return run


def build_scheduler(settings: Settings, database: Database, client: WeatherClient) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone=clock.SITE_TIME_ZONE)
    common = {"coalesce": True, "max_instances": 1, "misfire_grace_time": 3600, "replace_existing": True}
    scheduler.add_job(
        _guarded("report_reminders", lambda: run_report_reminders(database.session_factory)),
        CronTrigger(hour=settings.report_deadline_hour, minute=0, timezone=clock.SITE_TIME_ZONE),
        id="report_reminders",
        **common,
    )
    scheduler.add_job(
        _guarded("weather_refresh", lambda: refresh_weather(database.session_factory, client)),
        CronTrigger(hour=5, minute=30, timezone=clock.SITE_TIME_ZONE),
        id="weather_refresh",
        **common,
    )
    scheduler.add_job(
        _guarded("pour_check", lambda: run_pour_check(database.session_factory)),
        CronTrigger(hour=5, minute=45, timezone=clock.SITE_TIME_ZONE),  # BR-06, after the weather
        id="pour_check",
        **common,
    )
    scheduler.add_job(
        _guarded("risk_scoring", lambda: run_risk_scoring(database.session_factory)),
        CronTrigger(hour=6, minute=0, timezone=clock.SITE_TIME_ZONE),
        id="risk_scoring",
        **common,
    )
    scheduler.add_job(
        _guarded("variance_check", lambda: run_variance_check(database.session_factory)),
        CronTrigger(hour=6, minute=10, timezone=clock.SITE_TIME_ZONE),
        id="variance_check",
        **common,
    )
    return scheduler
