from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import ScanRunStatus, pg_enum


class ScanRun(Base):
    __tablename__ = "scan_runs"
    __table_args__ = (
        Index("idx_scan_runs_profile", "profile_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("scan_profiles.id", ondelete="CASCADE"))
    watchlist_id: Mapped[int] = mapped_column(ForeignKey("watchlists.id", ondelete="CASCADE"))
    status: Mapped[ScanRunStatus] = mapped_column(
        pg_enum(ScanRunStatus, "scan_run_status"),
        nullable=False,
        server_default="pending",
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    symbols_scanned: Mapped[int | None] = mapped_column(Integer, server_default="0")
    symbols_scored: Mapped[int | None] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    profile: Mapped["ScanProfile"] = relationship(back_populates="scan_runs")  # type: ignore[name-defined]
    watchlist: Mapped["Watchlist"] = relationship()  # type: ignore[name-defined]
    results: Mapped[list["ScanResult"]] = relationship(  # type: ignore[name-defined]
        back_populates="scan_run", cascade="all, delete-orphan"
    )
    signal_results: Mapped[list["SignalResult"]] = relationship(  # type: ignore[name-defined]
        back_populates="scan_run", cascade="all, delete-orphan"
    )
    pattern_detections: Mapped[list["PatternDetection"]] = relationship(  # type: ignore[name-defined]
        back_populates="scan_run", cascade="all, delete-orphan"
    )
    divergences: Mapped[list["Divergence"]] = relationship(  # type: ignore[name-defined]
        back_populates="scan_run", cascade="all, delete-orphan"
    )
