from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.enums import SALetterGrade, pg_enum


class SARating(Base):
    __tablename__ = "sa_ratings"
    __table_args__ = (
        Index("idx_sa_ratings_symbol_date", "symbol_id", "snapshot_date"),
        Index("idx_sa_ratings_momentum", "momentum_grade", "snapshot_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol_id: Mapped[int] = mapped_column(ForeignKey("symbols.id", ondelete="CASCADE"))
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Summary scores
    quant_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    sa_analyst_score: Mapped[float | None] = mapped_column(Numeric(4, 2))
    wall_st_score: Mapped[float | None] = mapped_column(Numeric(4, 2))

    # Quant factor grades
    valuation_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )
    growth_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )
    profitability_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )
    momentum_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )
    eps_revision_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )

    # Dividend grades
    div_safety_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )
    div_growth_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )
    div_yield_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )
    div_consistency_grade: Mapped[SALetterGrade | None] = mapped_column(
        pg_enum(SALetterGrade, "sa_letter_grade")
    )

    # Dividend metrics
    yield_fwd: Mapped[float | None] = mapped_column(Numeric(8, 6))
    payout_ratio: Mapped[float | None] = mapped_column(Numeric(8, 6))
    div_growth_3y: Mapped[float | None] = mapped_column(Numeric(8, 6))
    div_growth_5y: Mapped[float | None] = mapped_column(Numeric(8, 6))
    years_of_growth: Mapped[int | None] = mapped_column(Integer)
    div_frequency: Mapped[str | None] = mapped_column(String(20))

    # Risk
    beta_24m: Mapped[float | None] = mapped_column(Numeric(8, 6))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Relationships
    symbol: Mapped["Symbol"] = relationship(back_populates="sa_ratings")  # type: ignore[name-defined]
