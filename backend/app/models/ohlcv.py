from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import TimeframeEnum, pg_enum


class OHLCV(Base):
    """Price bar hypertable. No surrogate PK — composite (time, symbol_id, timeframe) is identity."""

    __tablename__ = "ohlcv"
    __table_args__ = (
        UniqueConstraint("time", "symbol_id", "timeframe"),
        Index("idx_ohlcv_symbol_tf_time", "symbol_id", "timeframe", "time"),
    )

    # Declared as primary_key for SQLAlchemy ORM identity; Postgres has no PK constraint.
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), primary_key=True
    )
    timeframe: Mapped[TimeframeEnum] = mapped_column(
        pg_enum(TimeframeEnum, "timeframe"), primary_key=True
    )

    open: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    high: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    low: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    close: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    volume: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric(20, 8))
