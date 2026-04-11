"""SentimentData model — AAII and NAAIM weekly sentiment readings."""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SentimentData(Base):
    __tablename__ = "sentiment_data"
    __table_args__ = (UniqueConstraint("source", "week_ending", name="uq_sentiment_source_week"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    week_ending: Mapped[date_type] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    extra: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
