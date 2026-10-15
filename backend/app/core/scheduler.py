"""Scheduled jobs (APScheduler, in-process).

- 18:00 site time: remind sites that have not filed today's report (BR-07).
- 05:30 site time: refresh the weather forecast for every active site.
- 06:00 site time: re-score every open project's risk (Phase 6), after the weather is fresh.
- Every minute: send the emails waiting in the outbox (Phase 11).
- 18:30 site time (``digest_hour``, ``digest_minute``): queue each user's evening digest.
- Monday 07:00 site time: queue the weekly PDF for project managers and quantity surveyors who take it.
- 03:00 site time, demo mode only: reset the demo to its seeded data (Phase 13).

Jobs are safe to run more than once (several API workers, a restart, the CLI): reminders are
de-duplicated in the database and weather refresh is an upsert. Each job opens its own session
and never lets an exception escape into the scheduler thread.
"""

from collections.abc import Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import clock
from app.core.config import Settings
from app.core.database import Database
from app.core.logging import get_logger
from app.integrations.weather import WeatherClient, WeatherUnavailableError
from app.models import Site
from app.services import (
    alerts,
    channels,
    cost_service,
    network_service,
    report_service,
    risk_service,
    weather,
    weekly_report,
)

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


def run_outbox(session_factory: Callable[[], Session], settings: Settings) -> tuple[int, int]:
    with session_factory() as db:
        return channels.send_pending(db, settings)


def run_digests(session_factory: Callable[[], Session]) -> int:
    with session_factory() as db:
        queued = alerts.queue_digests(db)
    log.info("digests_queued", queued=queued)
    return queued


def run_weekly_reports(session_factory: Callable[[], Session]) -> int:
    with session_factory() as db:
        queued = weekly_report.queue_weekly(db)
    log.info("weekly_reports_queued", queued=queued)
    return queued


def run_demo_reset() -> int:
    # Imported here: the CLI imports this module for the other jobs.
    from app.cli import reset_demo

    return reset_demo()


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
    scheduler.add_job(
        _guarded("email_outbox", lambda: run_outbox(database.session_factory, settings)),
        IntervalTrigger(minutes=1, timezone=clock.SITE_TIME_ZONE),
        id="email_outbox",
        **{**common, "misfire_grace_time": 60},
    )
    scheduler.add_job(
        _guarded("email_digest", lambda: run_digests(database.session_factory)),
        CronTrigger(hour=settings.digest_hour, minute=settings.digest_minute, timezone=clock.SITE_TIME_ZONE),
        id="email_digest",
        **common,
    )
    scheduler.add_job(
        _guarded("weekly_report", lambda: run_weekly_reports(database.session_factory)),
        CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=clock.SITE_TIME_ZONE),
        id="weekly_report",
        **common,
    )
    if settings.demo_mode:
        scheduler.add_job(
            _guarded("demo_reset", run_demo_reset),
            CronTrigger(hour=3, minute=0, timezone=clock.SITE_TIME_ZONE),
            id="demo_reset",
            **common,
        )
    return scheduler
