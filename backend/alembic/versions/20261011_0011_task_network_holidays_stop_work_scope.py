"""Phase 9: task dependencies, holidays, the working week, actual dates, pours and stop-work scope.

- Tasks gain actual start and finish dates, backfilled from daily-report history (the first report
  with progress, else the planned start; the last progress update for finished tasks). The hand-set
  ``is_critical`` flag goes: the critical path is now calculated.
- Existing stop-work flags had no task list, so they stop the whole project (the safe reading).
- The 2026 Sri Lankan public and Poya holidays are seeded from the official calendar as published,
  with the day after Vesak moved from 2 May to 31 May by the Minister's amendment of 21 April 2026.
  The Company Admin can correct them in the app.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-11 12:02:53.395265+00:00
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | Sequence[str] | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "holidays",
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_holidays_created_by_users"), ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_holidays")),
        sa.UniqueConstraint("holiday_date", name=op.f("uq_holidays_holiday_date")),
    )
    op.create_table(
        "task_dependencies",
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("predecessor_id", sa.Uuid(), nullable=False),
        sa.Column("successor_id", sa.Uuid(), nullable=False),
        sa.Column("lag_days", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.CheckConstraint("lag_days BETWEEN 0 AND 365", name=op.f("ck_task_dependencies_lag_range")),
        sa.CheckConstraint("predecessor_id <> successor_id", name=op.f("ck_task_dependencies_not_self")),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_task_dependencies_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["predecessor_id"],
            ["tasks.id"],
            name=op.f("fk_task_dependencies_predecessor_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_task_dependencies_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["successor_id"],
            ["tasks.id"],
            name=op.f("fk_task_dependencies_successor_id_tasks"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_dependencies")),
        sa.UniqueConstraint("predecessor_id", "successor_id", name="uq_task_dependencies_pair"),
    )
    op.create_index(
        op.f("ix_task_dependencies_project_id"), "task_dependencies", ["project_id"], unique=False
    )
    op.create_index("ix_task_dependencies_successor", "task_dependencies", ["successor_id"], unique=False)
    op.create_table(
        "report_action_tasks",
        sa.Column("action_id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["report_actions.id"],
            name=op.f("fk_report_action_tasks_action_id_report_actions"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_report_action_tasks_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("action_id", "task_id", name=op.f("pk_report_action_tasks")),
    )
    op.create_index(op.f("ix_report_action_tasks_task_id"), "report_action_tasks", ["task_id"], unique=False)
    op.add_column(
        "projects", sa.Column("working_week", sa.String(length=7), server_default="123456", nullable=False)
    )
    op.add_column("report_actions", sa.Column("stop_scope", sa.String(length=8), nullable=True))
    op.add_column(
        "tasks", sa.Column("is_concrete_pour", sa.Boolean(), server_default="false", nullable=False)
    )
    op.add_column("tasks", sa.Column("actual_start", sa.Date(), nullable=True))
    op.add_column("tasks", sa.Column("actual_finish", sa.Date(), nullable=True))
    op.drop_column("tasks", "is_critical")
    # Actual dates from the daily-report history.
    op.execute(
        """
        UPDATE tasks t SET actual_start = COALESCE(
            (SELECT min(r.report_date) FROM report_progress p JOIN daily_reports r ON r.id = p.report_id
             WHERE p.task_id = t.id AND p.percent_after > 0),
            t.planned_start)
        WHERE t.percent_complete > 0
        """
    )
    op.execute(
        """
        UPDATE tasks SET actual_finish = GREATEST(
            COALESCE((progress_updated_at AT TIME ZONE 'Asia/Colombo')::date, planned_end), actual_start)
        WHERE percent_complete = 100
        """
    )
    op.create_check_constraint(
        op.f("ck_tasks_started_when_progress"), "tasks", "(percent_complete > 0) = (actual_start IS NOT NULL)"
    )
    op.create_check_constraint(
        op.f("ck_tasks_finished_when_done"), "tasks", "(percent_complete = 100) = (actual_finish IS NOT NULL)"
    )
    op.create_check_constraint(
        op.f("ck_tasks_actual_dates_in_order"),
        "tasks",
        "actual_finish IS NULL OR actual_finish >= actual_start",
    )
    op.create_check_constraint(
        op.f("ck_projects_working_week_format"), "projects", "working_week ~ '^[1-7]{1,7}$'"
    )
    op.execute("UPDATE report_actions SET stop_scope = 'project' WHERE kind = 'stop_work'")
    op.create_check_constraint(
        op.f("ck_report_actions_stop_scope_for_stop_work"),
        "report_actions",
        "(kind = 'stop_work') = (stop_scope IS NOT NULL) "
        "AND (stop_scope IS NULL OR stop_scope IN ('tasks', 'project'))",
    )
    holidays = sa.table(
        "holidays",
        sa.column("id", sa.Uuid()),
        sa.column("holiday_date", sa.Date()),
        sa.column("name", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    seeded_at = datetime(2026, 10, 11, tzinfo=UTC)
    op.bulk_insert(
        holidays,
        [
            {"id": uuid.uuid4(), "holiday_date": date.fromisoformat(d), "name": n, "created_at": seeded_at}
            for d, n in HOLIDAYS_2026
        ],
    )


HOLIDAYS_2026 = [
    ("2026-01-03", "Duruthu Full Moon Poya Day"),
    ("2026-01-15", "Tamil Thai Pongal Day"),
    ("2026-02-01", "Navam Full Moon Poya Day"),
    ("2026-02-04", "Independence Day"),
    ("2026-02-15", "Maha Shivaratri Day"),
    ("2026-03-02", "Medin Full Moon Poya Day"),
    ("2026-03-21", "Eid-ul-Fitr (Ramazan Festival Day)"),
    ("2026-04-01", "Bak Full Moon Poya Day"),
    ("2026-04-03", "Good Friday"),
    ("2026-04-13", "Day before Sinhala and Tamil New Year"),
    ("2026-04-14", "Sinhala and Tamil New Year Day"),
    ("2026-05-01", "Vesak Full Moon Poya Day and May Day"),
    ("2026-05-28", "Eid al-Adha (Hajj Festival Day)"),
    ("2026-05-30", "Adhi Poson Full Moon Poya Day"),
    ("2026-05-31", "Day after Vesak (moved from 2 May)"),
    ("2026-06-29", "Poson Full Moon Poya Day"),
    ("2026-07-29", "Esala Full Moon Poya Day"),
    ("2026-08-26", "Milad-un-Nabi (Prophet's Birthday)"),
    ("2026-08-27", "Nikini Full Moon Poya Day"),
    ("2026-09-26", "Binara Full Moon Poya Day"),
    ("2026-10-25", "Vap Full Moon Poya Day"),
    ("2026-11-08", "Deepavali Festival Day"),
    ("2026-11-24", "Il Full Moon Poya Day"),
    ("2026-12-23", "Unduvap Full Moon Poya Day"),
    ("2026-12-25", "Christmas Day"),
]


def downgrade() -> None:
    op.drop_constraint(op.f("ck_report_actions_stop_scope_for_stop_work"), "report_actions", type_="check")
    op.drop_constraint(op.f("ck_projects_working_week_format"), "projects", type_="check")
    op.drop_constraint(op.f("ck_tasks_actual_dates_in_order"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_tasks_finished_when_done"), "tasks", type_="check")
    op.drop_constraint(op.f("ck_tasks_started_when_progress"), "tasks", type_="check")
    op.add_column(
        "tasks",
        sa.Column(
            "is_critical", sa.BOOLEAN(), server_default=sa.text("false"), autoincrement=False, nullable=False
        ),
    )
    op.drop_column("tasks", "actual_finish")
    op.drop_column("tasks", "actual_start")
    op.drop_column("tasks", "is_concrete_pour")
    op.drop_column("report_actions", "stop_scope")
    op.drop_column("projects", "working_week")
    op.drop_index(op.f("ix_report_action_tasks_task_id"), table_name="report_action_tasks")
    op.drop_table("report_action_tasks")
    op.drop_index("ix_task_dependencies_successor", table_name="task_dependencies")
    op.drop_index(op.f("ix_task_dependencies_project_id"), table_name="task_dependencies")
    op.drop_table("task_dependencies")
    op.drop_table("holidays")
