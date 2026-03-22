"""SQLAlchemy models — import all so Base.metadata is fully populated for Alembic."""

from app.models.backtest import BacktestResultModel
from app.models.base import Base
from app.models.divergences import Divergence
from app.models.macro_series import MacroSeries
from app.models.market_regime import MarketRegimeModel
from app.models.sentiment_data import SentimentData
from app.models.enums import (
    PatternType,
    SALetterGrade,
    ScanRunStatus,
    SignalCategory,
    SignalDirection,
    TimeframeEnum,
)
from app.models.indicator_cache import IndicatorCache
from app.models.ingestion_log import IngestionLog
from app.models.ohlcv import OHLCV
from app.models.pattern_detections import PatternDetection
from app.models.sa_ratings import SARating
from app.models.scan_profiles import ScanProfile
from app.models.scan_results import ScanResult
from app.models.scan_runs import ScanRun
from app.models.signal_results import SignalResult
from app.models.swing_points import SwingPoint
from app.models.symbols import Symbol
from app.models.synthesis_result import SynthesisResult
from app.models.watchlists import Watchlist, WatchlistItem

__all__ = [
    "Base",
    # Enums
    "TimeframeEnum",
    "SignalDirection",
    "SignalCategory",
    "PatternType",
    "ScanRunStatus",
    "SALetterGrade",
    # Models
    "BacktestResultModel",
    "MacroSeries",
    "MarketRegimeModel",
    "SentimentData",
    "Symbol",
    "SARating",
    "Watchlist",
    "WatchlistItem",
    "OHLCV",
    "IndicatorCache",
    "ScanProfile",
    "ScanRun",
    "ScanResult",
    "SignalResult",
    "PatternDetection",
    "Divergence",
    "SwingPoint",
    "SynthesisResult",
    "IngestionLog",
]
