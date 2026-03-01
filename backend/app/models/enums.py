"""Python enums mirroring the PostgreSQL ENUM types in the schema.

All enums use create_type=False in mapped_column so SQLAlchemy never issues
CREATE TYPE statements — the migration handles that.
"""
import enum


class TimeframeEnum(str, enum.Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"
    MO1 = "1M"


class SignalDirection(str, enum.Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalCategory(str, enum.Enum):
    TREND = "trend"
    MOMENTUM = "momentum"
    VOLATILITY = "volatility"
    VOLUME = "volume"
    SUPPORT_RESISTANCE = "support_resistance"
    DIVERGENCE = "divergence"
    PATTERN = "pattern"


class PatternType(str, enum.Enum):
    HARMONIC = "harmonic"
    CANDLESTICK = "candlestick"
    CHART_GEOMETRIC = "chart_geometric"


class ScanRunStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SALetterGrade(str, enum.Enum):
    A_PLUS = "A+"
    A = "A"
    A_MINUS = "A-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"
    C_PLUS = "C+"
    C = "C"
    C_MINUS = "C-"
    D_PLUS = "D+"
    D = "D"
    D_MINUS = "D-"
    F = "F"
