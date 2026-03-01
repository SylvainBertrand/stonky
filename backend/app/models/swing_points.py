from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import TimeframeEnum


class SwingPoint(Base):
    __tablename__ = "swing_points"
    __table_args__ = (
        UniqueConstraint("symbol_id", "timeframe", "time", "type"),
        Index("idx_swing_points_lookup", "symbol_id", "timeframe", "time"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    timeframe: Mapped[TimeframeEnum] = mapped_column(
        Enum(TimeframeEnum, name="timeframe", create_type=False), nullable=False
    )
    time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    type: Mapped[str] = mapped_column(String(10), nullable=False)  # 'high' or 'low'
    price: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    strength: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
