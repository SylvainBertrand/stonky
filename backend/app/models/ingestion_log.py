from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.enums import TimeframeEnum


class IngestionLog(Base):
    __tablename__ = "ingestion_log"
    __table_args__ = (
        Index("idx_ingestion_log_symbol", "symbol_id", "timeframe", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    timeframe: Mapped[TimeframeEnum] = mapped_column(
        Enum(TimeframeEnum, name="timeframe", create_type=False), nullable=False
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    bars_fetched: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    latest_bar: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="success")
    error_message: Mapped[str | None] = mapped_column(Text)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
