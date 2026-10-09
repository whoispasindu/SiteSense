"""Phase 3: programme tasks and daily progress snapshots.

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "progress_snapshots",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("actual_percent", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "actual_percent >= 0 AND actual_percent <= 100",
            name=op.f("ck_progress_snapshots_actual_percent_range"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_progress_snapshots_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_progress_snapshots")),
        sa.UniqueConstraint("project_id", "snapshot_date", name="uq_progress_snapshots_project_date"),
    )
    op.create_table(
        "tasks",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("boq_section_id", sa.Uuid(), nullable=True),
        sa.Column("code", sa.String(length=16), nullable=True),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("planned_start", sa.Date(), nullable=False),
        sa.Column("planned_end", sa.Date(), nullable=False),
        sa.Column("weight", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("percent_complete", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("is_critical", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("progress_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "percent_complete >= 0 AND percent_complete <= 100", name=op.f("ck_tasks_percent_complete_range")
        ),
        sa.CheckConstraint("planned_end >= planned_start", name=op.f("ck_tasks_dates_in_order")),
        sa.CheckConstraint("weight > 0 AND weight <= 100", name=op.f("ck_tasks_weight_range")),
        sa.ForeignKeyConstraint(
            ["boq_section_id"],
            ["boq_sections.id"],
            name=op.f("fk_tasks_boq_section_id_boq_sections"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_tasks_project_id_projects"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(op.f("ix_tasks_project_id"), "tasks", ["project_id"], unique=False)
    op.create_index(
        "uq_tasks_project_code",
        "tasks",
        ["project_id", "code"],
        unique=True,
        postgresql_where="code IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_tasks_project_code", table_name="tasks", postgresql_where="code IS NOT NULL")
    op.drop_index(op.f("ix_tasks_project_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_table("progress_snapshots")
