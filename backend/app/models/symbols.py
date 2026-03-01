from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Symbol(Base):
    __tablename__ = "symbols"
    __table_args__ = (
        Index("idx_symbols_ticker", "ticker"),
        Index("idx_symbols_asset_type", "asset_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(String(255))
    exchange: Mapped[str | None] = mapped_column(String(20))
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False, server_default="stock")
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships (back-populated from child tables)
    sa_ratings: Mapped[list["SARating"]] = relationship(  # type: ignore[name-defined]
        back_populates="symbol", cascade="all, delete-orphan"
    )
    watchlist_items: Mapped[list["WatchlistItem"]] = relationship(  # type: ignore[name-defined]
        back_populates="symbol", cascade="all, delete-orphan"
    )
