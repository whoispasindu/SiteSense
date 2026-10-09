"""Phase 2: projects, BOQ sections and items, budget lines.

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-09
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("code", sa.String(length=24), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("site_id", sa.Uuid(), nullable=False),
        sa.Column("client_name", sa.String(length=160), nullable=False),
        sa.Column("project_type", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("contract_value", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("planned_end", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint(
            "project_type IN ('residential', 'commercial', 'mixed_use', 'industrial', 'institutional')",
            name=op.f("ck_projects_project_type_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('planning', 'active', 'on_hold', 'completed', 'cancelled')",
            name=op.f("ck_projects_status_valid"),
        ),
        sa.CheckConstraint("contract_value > 0", name=op.f("ck_projects_contract_value_positive")),
        sa.CheckConstraint("planned_end >= start_date", name=op.f("ck_projects_dates_in_order")),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], name=op.f("fk_projects_site_id_sites")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_projects")),
        sa.UniqueConstraint("code", name=op.f("uq_projects_code")),
    )
    op.create_index(op.f("ix_projects_site_id"), "projects", ["site_id"], unique=False)
    op.create_table(
        "boq_sections",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_boq_sections_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_sections")),
        sa.UniqueConstraint("project_id", "code", name="uq_boq_sections_project_code"),
    )
    op.create_table(
        "boq_items",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("item_code", sa.String(length=24), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("unit", sa.String(length=16), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=14, scale=3), nullable=False),
        sa.Column("rate", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("amount", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_boq_items_quantity_positive")),
        sa.CheckConstraint("rate >= 0", name=op.f("ck_boq_items_rate_non_negative")),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_boq_items_project_id_projects"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["boq_sections.id"],
            name=op.f("fk_boq_items_section_id_boq_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_boq_items")),
        sa.UniqueConstraint("project_id", "item_code", name="uq_boq_items_project_item_code"),
    )
    op.create_index("ix_boq_items_project_id", "boq_items", ["project_id"], unique=False)
    op.create_index(op.f("ix_boq_items_section_id"), "boq_items", ["section_id"], unique=False)
    op.create_table(
        "budget_lines",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("section_id", sa.Uuid(), nullable=False),
        sa.Column("budget_amount", sa.Numeric(precision=16, scale=2), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("budget_amount >= 0", name=op.f("ck_budget_lines_budget_amount_non_negative")),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_budget_lines_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["section_id"],
            ["boq_sections.id"],
            name=op.f("fk_budget_lines_section_id_boq_sections"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_budget_lines")),
        sa.UniqueConstraint("section_id", name=op.f("uq_budget_lines_section_id")),
    )
    op.create_index(op.f("ix_budget_lines_project_id"), "budget_lines", ["project_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_budget_lines_project_id"), table_name="budget_lines")
    op.drop_table("budget_lines")
    op.drop_index(op.f("ix_boq_items_section_id"), table_name="boq_items")
    op.drop_index("ix_boq_items_project_id", table_name="boq_items")
    op.drop_table("boq_items")
    op.drop_table("boq_sections")
    op.drop_index(op.f("ix_projects_site_id"), table_name="projects")
    op.drop_table("projects")
