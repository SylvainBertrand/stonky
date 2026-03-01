from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SignalCategory, SignalDirection, pg_enum


class SignalResult(Base):
    __tablename__ = "signal_results"
    __table_args__ = (
        Index("idx_signal_results_run_symbol", "scan_run_id", "symbol_id"),
        Index("idx_signal_results_category", "scan_run_id", "category"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id", ondelete="CASCADE"))
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    indicator_name: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[SignalCategory] = mapped_column(
        pg_enum(SignalCategory, "signal_category"), nullable=False
    )
    signal_value: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(
        pg_enum(SignalDirection, "signal_direction"), nullable=False
    )
    raw_values: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    signal_label: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scan_run: Mapped["ScanRun"] = relationship(back_populates="signal_results")  # type: ignore[name-defined]
    symbol: Mapped["Symbol"] = relationship()  # type: ignore[name-defined]
