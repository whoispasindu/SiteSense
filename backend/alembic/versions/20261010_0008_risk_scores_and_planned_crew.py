"""Phase 6: daily risk scores, and a project's planned crew size (a risk model input).

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "risk_scores",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("score_date", sa.Date(), nullable=False),
        sa.Column("score", sa.SmallInteger(), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        sa.Column("delay_days", sa.Numeric(precision=7, scale=1), nullable=False),
        sa.Column("overrun_pct", sa.Numeric(precision=6, scale=2), nullable=False),
        sa.Column("ranges", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("drivers", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("model_version", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("level IN ('low', 'medium', 'high')", name=op.f("ck_risk_scores_level_values")),
        sa.CheckConstraint("score >= 0 AND score <= 100", name=op.f("ck_risk_scores_score_range")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_risk_scores_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_risk_scores")),
        sa.UniqueConstraint("project_id", "score_date", name="uq_risk_scores_project_date"),
    )
    op.add_column("projects", sa.Column("planned_crew", sa.Integer(), nullable=True))
    op.create_check_constraint(
        "planned_crew_range", "projects", "planned_crew IS NULL OR planned_crew BETWEEN 1 AND 5000"
    )


def downgrade() -> None:
    op.drop_constraint("planned_crew_range", "projects", type_="check")
    op.drop_column("projects", "planned_crew")
    op.drop_table("risk_scores")
