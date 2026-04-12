"""Add synthesis_results table for LLM trade setup analysis.

Revision ID: 004
Revises: 003
Create Date: 2026-03-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "synthesis_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "symbol_id",
            sa.Integer(),
            sa.ForeignKey("symbols.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("setup_type", sa.String(50), nullable=False),
        sa.Column("bias", sa.String(10), nullable=False),
        sa.Column("confidence", sa.String(10), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("signal_confluence", sa.Text(), nullable=False),
        sa.Column("signal_conflicts", sa.Text(), nullable=False),
        sa.Column("entry", sa.Numeric(12, 4)),
        sa.Column("stop", sa.Numeric(12, 4)),
        sa.Column("target", sa.Numeric(12, 4)),
        sa.Column("risk_reward", sa.Numeric(6, 2)),
        sa.Column("key_risk", sa.Text(), nullable=False),
        sa.Column(
            "parse_error",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("raw_response", sa.Text()),
    )
    op.create_index(
        "idx_synthesis_symbol_date",
        "synthesis_results",
        ["symbol_id", sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_synthesis_symbol_date", table_name="synthesis_results")
    op.drop_table("synthesis_results")
