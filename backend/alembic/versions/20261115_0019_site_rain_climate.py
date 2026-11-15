"""Any country: each site's own rain climate, and Sri Lanka's 2026 holidays only in Sri Lanka.

- Sites gain ``rain_climate`` (12 monthly heavy-rain shares) and when it was fetched; the risk model
  uses it for sites outside Sri Lanka (``app/ai/risk/climate.py``).
- Migration 0011 seeded Sri Lanka's 2026 public and Poya holidays into every database. For a company
  in another country (``SITESENSE_COUNTRY`` is not LK) those seeded rows are removed here: the ones
  with no author, i.e. not added in the app. Its admin imports the country's own holidays instead.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-15 09:00:00.000000+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.core.config import get_settings

revision: str = "0019"
down_revision: str | Sequence[str] | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("sites", sa.Column("rain_climate", postgresql.ARRAY(sa.Float()), nullable=True))
    op.add_column("sites", sa.Column("rain_climate_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        op.f("ck_sites_rain_climate_months"), "sites", "rain_climate IS NULL OR cardinality(rain_climate) = 12"
    )
    if get_settings().country != "LK":
        op.execute(
            "DELETE FROM holidays WHERE created_by IS NULL "
            "AND holiday_date BETWEEN DATE '2026-01-01' AND DATE '2026-12-31'"
        )


def downgrade() -> None:
    # Removed seed holidays are not put back: the admin's holiday page can add them.
    op.drop_constraint(op.f("ck_sites_rain_climate_months"), "sites", type_="check")
    op.drop_column("sites", "rain_climate_at")
    op.drop_column("sites", "rain_climate")
