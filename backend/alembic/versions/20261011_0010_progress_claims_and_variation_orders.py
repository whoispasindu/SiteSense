"""Phase 8: progress claims, variation orders, the BR-09 variation limit and variance alerts.

Existing projects get a variation limit of 1% of their contract value (the BR-09 default).

Revision ID: 0010
Revises: 0009
Create Date: 2026-10-11 06:43:46.613695+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0010"
down_revision: str | Sequence[str] | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "progress_claims",
        sa.Column("number", sa.String(length=16), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("contract_value", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("certified_pct", sa.Numeric(precision=9, scale=6), nullable=False),
        sa.Column("certified_value", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("retention", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("previous_claims", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("amount", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("submitted_by", sa.Uuid(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_comment", sa.Text(), nullable=True),
        sa.Column("paid_on", sa.Date(), nullable=True),
        sa.Column("paid_recorded_by", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "(status = 'paid') = (paid_on IS NOT NULL)", name=op.f("ck_progress_claims_paid_on_when_paid")
        ),
        sa.CheckConstraint(
            "(status = 'submitted') = (decided_at IS NULL)",
            name=op.f("ck_progress_claims_decided_unless_submitted"),
        ),
        sa.CheckConstraint(
            "status IN ('submitted', 'approved', 'returned', 'paid')",
            name=op.f("ck_progress_claims_status_values"),
        ),
        sa.CheckConstraint(
            "amount + retention + previous_claims = certified_value",
            name=op.f("ck_progress_claims_br08_figures_add_up"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_progress_claims_amount_positive")),
        sa.CheckConstraint(
            "certified_pct BETWEEN 0 AND 100", name=op.f("ck_progress_claims_certified_pct_range")
        ),
        sa.CheckConstraint(
            "certified_value <= contract_value", name=op.f("ck_progress_claims_certified_within_contract")
        ),
        sa.CheckConstraint(
            "retention >= 0 AND previous_claims >= 0",
            name=op.f("ck_progress_claims_retention_previous_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_progress_claims_decided_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["paid_recorded_by"], ["users.id"], name=op.f("fk_progress_claims_paid_recorded_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_progress_claims_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["submitted_by"], ["users.id"], name=op.f("fk_progress_claims_submitted_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_progress_claims")),
        sa.UniqueConstraint("number", name=op.f("uq_progress_claims_number")),
    )
    op.create_index(
        "ix_progress_claims_project", "progress_claims", ["project_id", "submitted_at"], unique=False
    )
    op.create_index(
        "uq_progress_claims_one_submitted",
        "progress_claims",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text("status = 'submitted'"),
    )
    op.create_table(
        "progress_claim_lines",
        sa.Column("claim_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("section_value", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("certified_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("previous_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "certified_pct BETWEEN 0 AND 100", name=op.f("ck_progress_claim_lines_certified_pct_range")
        ),
        sa.CheckConstraint(
            "previous_pct BETWEEN 0 AND certified_pct",
            name=op.f("ck_progress_claim_lines_not_below_previous"),
        ),
        sa.CheckConstraint(
            "section_value >= 0", name=op.f("ck_progress_claim_lines_section_value_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["progress_claims.id"],
            name=op.f("fk_progress_claim_lines_claim_id_progress_claims"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"], ["boq_sections.id"], name=op.f("fk_progress_claim_lines_section_id_boq_sections")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_progress_claim_lines")),
        sa.UniqueConstraint("claim_id", "section_id", name="uq_progress_claim_lines_section"),
    )
    op.create_table(
        "variation_orders",
        sa.Column("number", sa.String(length=16), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("boq_item_id", sa.Uuid(), nullable=True),
        sa.Column("quantity_change", sa.Numeric(precision=14, scale=3), nullable=True),
        sa.Column("task_id", sa.Uuid(), nullable=True),
        sa.Column("time_impact_days", sa.Integer(), nullable=False),
        sa.Column("contract_change", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("budget_change", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("approver", sa.String(length=8), nullable=True),
        sa.Column("limit_applied", sa.Numeric(precision=16, scale=2), nullable=True),
        sa.Column("raised_by", sa.Uuid(), nullable=False),
        sa.Column("raised_by_role", sa.String(length=4), nullable=False),
        sa.Column("raised_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("priced_by", sa.Uuid(), nullable=True),
        sa.Column("priced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_to_client_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "approver IS NULL OR approver IN ('pm', 'client')",
            name=op.f("ck_variation_orders_approver_values"),
        ),
        sa.CheckConstraint(
            "raised_by_role IN ('pm', 'qs')", name=op.f("ck_variation_orders_raised_by_role_values")
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_pricing', 'awaiting_pm', 'awaiting_client', 'queried', 'approved', 'rejected', 'withdrawn')",
            name=op.f("ck_variation_orders_status_values"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('approved', 'rejected') OR decided_at IS NOT NULL",
            name=op.f("ck_variation_orders_decided_when_closed"),
        ),
        sa.CheckConstraint(
            "status NOT IN ('awaiting_pm', 'awaiting_client', 'approved') OR (contract_change IS NOT NULL AND approver IS NOT NULL AND limit_applied IS NOT NULL)",
            name=op.f("ck_variation_orders_priced_before_approval"),
        ),
        sa.CheckConstraint(
            "(boq_item_id IS NULL) = (quantity_change IS NULL)",
            name=op.f("ck_variation_orders_item_with_quantity"),
        ),
        sa.CheckConstraint(
            "(contract_change IS NULL) = (budget_change IS NULL)",
            name=op.f("ck_variation_orders_priced_together"),
        ),
        sa.CheckConstraint(
            "(contract_change IS NULL) = (priced_at IS NULL)",
            name=op.f("ck_variation_orders_priced_at_when_priced"),
        ),
        sa.CheckConstraint(
            "quantity_change IS NULL OR quantity_change > 0",
            name=op.f("ck_variation_orders_quantity_change_positive"),
        ),
        sa.CheckConstraint(
            "time_impact_days BETWEEN 0 AND 3650", name=op.f("ck_variation_orders_time_impact_range")
        ),
        sa.ForeignKeyConstraint(
            ["boq_item_id"], ["boq_items.id"], name=op.f("fk_variation_orders_boq_item_id_boq_items")
        ),
        sa.ForeignKeyConstraint(
            ["decided_by"], ["users.id"], name=op.f("fk_variation_orders_decided_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["priced_by"], ["users.id"], name=op.f("fk_variation_orders_priced_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_variation_orders_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["raised_by"], ["users.id"], name=op.f("fk_variation_orders_raised_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["section_id"], ["boq_sections.id"], name=op.f("fk_variation_orders_section_id_boq_sections")
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_variation_orders_task_id_tasks"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variation_orders")),
        sa.UniqueConstraint("number", name=op.f("uq_variation_orders_number")),
    )
    op.create_index(
        "ix_variation_orders_item_status", "variation_orders", ["boq_item_id", "status"], unique=False
    )
    op.create_index(
        "ix_variation_orders_project_status", "variation_orders", ["project_id", "status"], unique=False
    )
    op.create_table(
        "variation_events",
        sa.Column("variation_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("client_visible", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "action IN ('raised', 'priced', 'revised', 'approved', 'queried', 'rejected', 'withdrawn')",
            name=op.f("ck_variation_events_action_values"),
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], name=op.f("fk_variation_events_actor_id_users")),
        sa.ForeignKeyConstraint(
            ["variation_id"],
            ["variation_orders.id"],
            name=op.f("fk_variation_events_variation_id_variation_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_variation_events")),
    )
    op.create_index(
        op.f("ix_variation_events_variation_id"), "variation_events", ["variation_id"], unique=False
    )
    op.add_column("budget_lines", sa.Column("over_budget_since", sa.Date(), nullable=True))
    op.add_column("projects", sa.Column("variation_limit", sa.Numeric(precision=16, scale=2), nullable=True))
    op.execute("UPDATE projects SET variation_limit = round(contract_value * 0.01, 2)")
    op.alter_column("projects", "variation_limit", nullable=False)
    op.create_check_constraint(
        op.f("ck_projects_variation_limit_non_negative"), "projects", "variation_limit >= 0"
    )


def downgrade() -> None:
    op.drop_constraint(op.f("ck_projects_variation_limit_non_negative"), "projects", type_="check")
    op.drop_column("projects", "variation_limit")
    op.drop_column("budget_lines", "over_budget_since")
    op.drop_index(op.f("ix_variation_events_variation_id"), table_name="variation_events")
    op.drop_table("variation_events")
    op.drop_index("ix_variation_orders_project_status", table_name="variation_orders")
    op.drop_index("ix_variation_orders_item_status", table_name="variation_orders")
    op.drop_table("variation_orders")
    op.drop_table("progress_claim_lines")
    op.drop_index(
        "uq_progress_claims_one_submitted",
        table_name="progress_claims",
        postgresql_where=sa.text("status = 'submitted'"),
    )
    op.drop_index("ix_progress_claims_project", table_name="progress_claims")
    op.drop_table("progress_claims")
