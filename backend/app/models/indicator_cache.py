from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import TimeframeEnum


class IndicatorCache(Base):
    """Precomputed indicator values hypertable. Composite identity, no surrogate PK."""

    __tablename__ = "indicator_cache"
    __table_args__ = (
        UniqueConstraint("time", "symbol_id", "timeframe", "indicator_name", "params_hash"),
        Index(
            "idx_indicator_cache_lookup",
            "symbol_id", "timeframe", "indicator_name", "time",
        ),
    )

    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), primary_key=True
    )
    timeframe: Mapped[TimeframeEnum] = mapped_column(
        Enum(TimeframeEnum, name="timeframe", create_type=False), primary_key=True
    )
    indicator_name: Mapped[str] = mapped_column(String(50), primary_key=True)
    params_hash: Mapped[str] = mapped_column(String(32), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
