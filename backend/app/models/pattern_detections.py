from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import PatternType, SignalDirection, TimeframeEnum


class PatternDetection(Base):
    __tablename__ = "pattern_detections"
    __table_args__ = (
        Index("idx_pattern_detections_run_symbol", "scan_run_id", "symbol_id"),
        Index("idx_pattern_detections_type", "pattern_type", "pattern_name"),
        Index("idx_pattern_detections_detected", "detected_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id", ondelete="CASCADE"))
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    timeframe: Mapped[TimeframeEnum] = mapped_column(
        Enum(TimeframeEnum, name="timeframe", create_type=False), nullable=False
    )
    pattern_type: Mapped[PatternType] = mapped_column(
        Enum(PatternType, name="pattern_type", create_type=False), nullable=False
    )
    pattern_name: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(
        Enum(SignalDirection, name="signal_direction", create_type=False), nullable=False
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    geometry: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invalidation: Mapped[float | None] = mapped_column(Numeric(20, 8))
    targets: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scan_run: Mapped["ScanRun"] = relationship(back_populates="pattern_detections")  # type: ignore[name-defined]
    symbol: Mapped["Symbol"] = relationship()  # type: ignore[name-defined]
