from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ForecastCache(Base):
    __tablename__ = "forecast_cache"
    __table_args__ = (
        Index(
            "idx_forecast_cache_symbol_tf",
            "symbol_id",
            "timeframe",
            "generated_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False
    )
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    horizon_bars: Mapped[int] = mapped_column(Integer, nullable=False)
    last_bar_date: Mapped[date] = mapped_column(Date, nullable=False)
    last_close: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    median: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quantile_10: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quantile_25: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quantile_75: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    quantile_90: Mapped[list[float]] = mapped_column(JSONB, nullable=False)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    direction_confidence: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False
    )
    expected_move_pct: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False
    )

    symbol: Mapped["Symbol"] = relationship()  # type: ignore[name-defined]
