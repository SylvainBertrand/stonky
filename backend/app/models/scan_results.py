from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SignalDirection


class ScanResult(Base):
    __tablename__ = "scan_results"
    __table_args__ = (
        UniqueConstraint("scan_run_id", "symbol_id"),
        Index("idx_scan_results_run_rank", "scan_run_id", "rank"),
        Index("idx_scan_results_symbol", "symbol_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    scan_run_id: Mapped[int] = mapped_column(ForeignKey("scan_runs.id", ondelete="CASCADE"))
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    composite_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    direction: Mapped[SignalDirection] = mapped_column(
        Enum(SignalDirection, name="signal_direction", create_type=False), nullable=False
    )
    category_scores: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    profile_matches: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default="'[]'"
    )
    risk_reward: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    categories_agreeing: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rank: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scan_run: Mapped["ScanRun"] = relationship(back_populates="results")  # type: ignore[name-defined]
    symbol: Mapped["Symbol"] = relationship()  # type: ignore[name-defined]
