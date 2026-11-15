"""Each site's own rain climate, for sites outside Sri Lanka (see ``ai/risk/climate.py``).

Fetched once, with the morning weather refresh (and ``python -m app.cli refresh-weather``), for every
active site that has coordinates outside Sri Lanka and no climate yet. Moving a site clears it, so
the next refresh fetches the new place's. A failed fetch is retried the next morning; until then the
risk model uses the seven towns' average and says so.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.risk import climate
from app.core import clock
from app.integrations.climate import ClimateClient
from app.integrations.weather import WeatherUnavailableError
from app.models import Site


def sites_needing_climate(db: Session) -> list[Site]:
    candidates = db.scalars(
        select(Site).where(
            Site.is_active.is_(True),
            Site.latitude.is_not(None),
            Site.longitude.is_not(None),
            Site.rain_climate.is_(None),
        )
    ).all()
    return [s for s in candidates if climate.needs_own(s.latitude, s.longitude)]


def refresh(db: Session, site: Site, client: ClimateClient) -> None:
    """Fetch and store the site's monthly heavy-rain shares. Raises ``WeatherUnavailableError``."""
    if site.latitude is None or site.longitude is None:
        return
    days, rain = client.daily_rain(site.latitude, site.longitude)
    try:
        shares = climate.heavy_day_shares(days, rain)
    except climate.ClimateError as exc:
        raise WeatherUnavailableError(str(exc)) from exc
    site.rain_climate = list(shares)
    site.rain_climate_at = clock.utcnow()
    db.commit()
