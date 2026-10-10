"""Phase 5: a material request's price may be pending until the QS enters the quote.

Revision ID: 0007
Revises: 0006
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | Sequence[str] | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # The check "unit_price > 0" stays: it is satisfied by NULL and still refuses zero or negative.
    op.alter_column("material_requests", "unit_price", existing_type=sa.Numeric(14, 2), nullable=True)


def downgrade() -> None:
    op.execute(
        "UPDATE material_requests SET unit_price = 0.01 WHERE unit_price IS NULL"  # noqa: S608 - constant SQL
    )
    op.alter_column("material_requests", "unit_price", existing_type=sa.Numeric(14, 2), nullable=False)
