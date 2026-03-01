from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ScanProfile(Base):
    __tablename__ = "scan_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    indicators: Mapped[list[Any]] = mapped_column(JSONB, nullable=False, server_default="'[]'")
    category_weights: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    filters: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    timeframes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="'{}'"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    scan_runs: Mapped[list["ScanRun"]] = relationship(  # type: ignore[name-defined]
        back_populates="profile", cascade="all, delete-orphan"
    )
