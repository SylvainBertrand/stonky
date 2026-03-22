"""MarketRegimeModel — daily market regime classification."""
from __future__ import annotations

from datetime import date as date_type

from sqlalchemy import Date, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MarketRegimeModel(Base):
    __tablename__ = "market_regime"

    id: Mapped[int] = mapped_column(primary_key=True)
    as_of_date: Mapped[date_type] = mapped_column(Date, nullable=False, unique=True)
    regime: Mapped[str] = mapped_column(String(20), nullable=False)
    breadth: Mapped[str] = mapped_column(String(10), nullable=False)
    momentum: Mapped[str] = mapped_column(String(10), nullable=False)
    sentiment: Mapped[str] = mapped_column(String(15), nullable=False)
    macro: Mapped[str] = mapped_column(String(15), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    scanner_implication: Mapped[str] = mapped_column(Text, nullable=False)
