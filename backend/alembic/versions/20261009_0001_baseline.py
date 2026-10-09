"""Baseline: empty schema that every later migration builds on.

Revision ID: 0001
Revises:
Create Date: 2026-10-09
"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Phase 0 ships no tables. Phase 1 adds users, roles and audit logs."""


def downgrade() -> None:
    pass
