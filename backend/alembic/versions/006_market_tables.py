"""Add market analysis tables (macro_series, sentiment_data, market_regime).

Revision ID: 006
Revises: 005
Create Date: 2026-03-15
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "006"
down_revision = "005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "macro_series",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("series_id", sa.String(20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(12, 4), nullable=True),
        sa.UniqueConstraint("series_id", "date", name="uq_macro_series_sid_date"),
    )
    op.create_index(
        "idx_macro_series_lookup", "macro_series", ["series_id", sa.text("date DESC")]
    )

    op.create_table(
        "sentiment_data",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("week_ending", sa.Date(), nullable=False),
        sa.Column("value", sa.Numeric(8, 4), nullable=False),
        sa.Column("extra", JSONB(), nullable=True),
        sa.UniqueConstraint("source", "week_ending", name="uq_sentiment_source_week"),
    )

    op.create_table(
        "market_regime",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("as_of_date", sa.Date(), nullable=False, unique=True),
        sa.Column("regime", sa.String(20), nullable=False),
        sa.Column("breadth", sa.String(10), nullable=False),
        sa.Column("momentum", sa.String(10), nullable=False),
        sa.Column("sentiment", sa.String(15), nullable=False),
        sa.Column("macro", sa.String(15), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("scanner_implication", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("market_regime")
    op.drop_table("sentiment_data")
    op.drop_table("macro_series")
