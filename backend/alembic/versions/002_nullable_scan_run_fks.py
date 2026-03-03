"""Make scan_runs.profile_id and watchlist_id nullable.

Revision ID: 002
Revises: 001
Create Date: 2026-03-02
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Make profile_id nullable (scan may run without a stored profile)
    op.alter_column(
        "scan_runs",
        "profile_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    # Drop CASCADE FK and re-add as SET NULL so deleting a profile doesn't cascade-delete runs
    op.drop_constraint("scan_runs_profile_id_fkey", "scan_runs", type_="foreignkey")
    op.create_foreign_key(
        "scan_runs_profile_id_fkey",
        "scan_runs",
        "scan_profiles",
        ["profile_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Make watchlist_id nullable (scan runs should persist even if watchlist is deleted)
    op.alter_column(
        "scan_runs",
        "watchlist_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.drop_constraint("scan_runs_watchlist_id_fkey", "scan_runs", type_="foreignkey")
    op.create_foreign_key(
        "scan_runs_watchlist_id_fkey",
        "scan_runs",
        "watchlists",
        ["watchlist_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Restore NOT NULL — delete orphaned rows first
    op.execute("DELETE FROM scan_runs WHERE profile_id IS NULL OR watchlist_id IS NULL")

    op.drop_constraint("scan_runs_profile_id_fkey", "scan_runs", type_="foreignkey")
    op.create_foreign_key(
        "scan_runs_profile_id_fkey",
        "scan_runs",
        "scan_profiles",
        ["profile_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("scan_runs", "profile_id", existing_type=sa.Integer(), nullable=False)

    op.drop_constraint("scan_runs_watchlist_id_fkey", "scan_runs", type_="foreignkey")
    op.create_foreign_key(
        "scan_runs_watchlist_id_fkey",
        "scan_runs",
        "watchlists",
        ["watchlist_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.alter_column("scan_runs", "watchlist_id", existing_type=sa.Integer(), nullable=False)
