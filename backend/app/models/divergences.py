from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SignalDirection, TimeframeEnum


class Divergence(Base):
    __tablename__ = "divergences"
    __table_args__ = (
        Index("idx_divergences_run_symbol", "scan_run_id", "symbol_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id", ondelete="CASCADE"))
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    timeframe: Mapped[TimeframeEnum] = mapped_column(
        Enum(TimeframeEnum, name="timeframe", create_type=False), nullable=False
    )
    indicator_name: Mapped[str] = mapped_column(String(50), nullable=False)
    divergence_type: Mapped[str] = mapped_column(String(20), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(
        Enum(SignalDirection, name="signal_direction", create_type=False), nullable=False
    )
    pivots: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scan_run: Mapped["ScanRun"] = relationship(back_populates="divergences")  # type: ignore[name-defined]
    symbol: Mapped["Symbol"] = relationship()  # type: ignore[name-defined]
