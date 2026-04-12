"""Add forecast_cache table for Chronos-2 price forecasts.

Revision ID: 003
Revises: 002
Create Date: 2026-03-08
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "forecast_cache",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "symbol_id",
            sa.Integer(),
            sa.ForeignKey("symbols.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_bars", sa.Integer(), nullable=False),
        sa.Column("last_bar_date", sa.Date(), nullable=False),
        sa.Column("last_close", sa.Numeric(12, 4), nullable=False),
        sa.Column("median", JSONB(), nullable=False),
        sa.Column("quantile_10", JSONB(), nullable=False),
        sa.Column("quantile_25", JSONB(), nullable=False),
        sa.Column("quantile_75", JSONB(), nullable=False),
        sa.Column("quantile_90", JSONB(), nullable=False),
        sa.Column("direction", sa.String(10), nullable=False),
        sa.Column("direction_confidence", sa.Numeric(5, 4), nullable=False),
        sa.Column("expected_move_pct", sa.Numeric(7, 4), nullable=False),
    )
    op.create_index(
        "idx_forecast_cache_symbol_tf",
        "forecast_cache",
        ["symbol_id", "timeframe", sa.text("generated_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("idx_forecast_cache_symbol_tf", table_name="forecast_cache")
    op.drop_table("forecast_cache")
