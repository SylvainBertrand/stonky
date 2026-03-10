from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class SynthesisResult(Base):
    __tablename__ = "synthesis_results"
    __table_args__ = (
        Index(
            "idx_synthesis_symbol_date",
            "symbol_id",
            "generated_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    setup_type: Mapped[str] = mapped_column(String(50), nullable=False)
    bias: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[str] = mapped_column(String(10), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    signal_confluence: Mapped[str] = mapped_column(Text, nullable=False)
    signal_conflicts: Mapped[str] = mapped_column(Text, nullable=False)
    entry: Mapped[float | None] = mapped_column(Numeric(12, 4))
    stop: Mapped[float | None] = mapped_column(Numeric(12, 4))
    target: Mapped[float | None] = mapped_column(Numeric(12, 4))
    risk_reward: Mapped[float | None] = mapped_column(Numeric(6, 2))
    key_risk: Mapped[str] = mapped_column(Text, nullable=False)
    parse_error: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    raw_response: Mapped[str | None] = mapped_column(Text)

    symbol: Mapped["Symbol"] = relationship()  # type: ignore[name-defined]
