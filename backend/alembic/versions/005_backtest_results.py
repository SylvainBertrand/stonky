"""Add backtest_results table for storing backtest runs.

Revision ID: 005
Revises: 004
Create Date: 2026-03-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("timeframe", sa.String(10), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("strategy", sa.String(50), nullable=False),
        sa.Column("parameters", JSONB(), nullable=False),
        sa.Column("stats", JSONB(), nullable=False),
        sa.Column("equity", JSONB(), nullable=False),
        sa.Column("drawdown", JSONB(), nullable=False),
        sa.Column("trades", JSONB(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("backtest_results")
