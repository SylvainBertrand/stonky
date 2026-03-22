"""MacroSeries model — FRED economic data time series."""
from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from sqlalchemy import Date, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MacroSeries(Base):
    __tablename__ = "macro_series"
    __table_args__ = (UniqueConstraint("series_id", "date", name="uq_macro_series_sid_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date_type] = mapped_column(Date, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
