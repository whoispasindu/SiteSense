"""Phase 7: issues tagged in daily reports, and the follow-up actions they create.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | Sequence[str] | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "report_issues",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("source", sa.String(length=8), nullable=False),
        sa.Column("ai_category", sa.String(length=20), nullable=True),
        sa.Column("ai_severity", sa.String(length=8), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=4, scale=3), nullable=True),
        sa.Column("low_confidence", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("model_version", sa.String(length=16), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_by", sa.Uuid(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "category IN ('material_delay', 'labour', 'weather', 'equipment', 'safety', 'design', 'quality', 'other')",
            name=op.f("ck_report_issues_category_values"),
        ),
        sa.CheckConstraint(
            "severity IN ('low', 'medium', 'high')", name=op.f("ck_report_issues_severity_values")
        ),
        sa.CheckConstraint("source IN ('ai', 'manual')", name=op.f("ck_report_issues_source_values")),
        sa.CheckConstraint(
            "status IN ('suggested', 'confirmed', 'removed')", name=op.f("ck_report_issues_status_values")
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_report_issues_confidence_range"),
        ),
        sa.CheckConstraint("length(snippet) BETWEEN 1 AND 500", name=op.f("ck_report_issues_snippet_length")),
        sa.ForeignKeyConstraint(
            ["confirmed_by"], ["users.id"], name=op.f("fk_report_issues_confirmed_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_report_issues_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["daily_reports.id"],
            name=op.f("fk_report_issues_report_id_daily_reports"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_issues")),
    )
    op.create_index(
        "ix_report_issues_project_status",
        "report_issues",
        ["project_id", "status", "confirmed_at"],
        unique=False,
    )
    op.create_index("ix_report_issues_report", "report_issues", ["report_id", "position"], unique=False)
    op.create_table(
        "report_actions",
        sa.Column("report_id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_by", sa.Uuid(), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'open') = (closed_at IS NULL)", name=op.f("ck_report_actions_closed_when_not_open")
        ),
        sa.CheckConstraint(
            "kind IN ('material_request', 'pm_alert', 'stop_work')",
            name=op.f("ck_report_actions_kind_values"),
        ),
        sa.CheckConstraint(
            "status IN ('open', 'done', 'dismissed')", name=op.f("ck_report_actions_status_values")
        ),
        sa.ForeignKeyConstraint(["closed_by"], ["users.id"], name=op.f("fk_report_actions_closed_by_users")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_report_actions_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_report_actions_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["report_id"],
            ["daily_reports.id"],
            name=op.f("fk_report_actions_report_id_daily_reports"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["material_requests.id"],
            name=op.f("fk_report_actions_request_id_material_requests"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_actions")),
    )
    op.create_index(
        "ix_report_actions_project_open", "report_actions", ["project_id", "kind", "status"], unique=False
    )
    op.create_index("ix_report_actions_report", "report_actions", ["report_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_report_actions_report", table_name="report_actions")
    op.drop_index("ix_report_actions_project_open", table_name="report_actions")
    op.drop_table("report_actions")
    op.drop_index("ix_report_issues_report", table_name="report_issues")
    op.drop_index("ix_report_issues_project_status", table_name="report_issues")
    op.drop_table("report_issues")
