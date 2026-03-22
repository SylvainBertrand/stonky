"""
Pydantic schemas for the scanner API.
"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.patterns import PatternDetectionResponse


class CategoryScores(BaseModel):
    trend: float = 0.0
    momentum: float = 0.0
    volume: float = 0.0
    volatility: float = 0.0
    support_resistance: float = 0.0
    divergence: float = 0.0
    pattern: float = 0.0


class AnalysisMeta(BaseModel):
    atr: float
    atr_pct: float
    last_price: float
    volume_ratio: float = 0.0
    price_change_pct: float = 0.0
    timestamp: str
    bars: int = 0


class HarmonicInfo(BaseModel):
    """Harmonic pattern detail for the API response."""

    detected: bool
    pattern: str | None = None
    direction: str | None = None
    ratio_quality: float = 0.0
    in_prz: bool = False
    prz_low: float | None = None
    prz_high: float | None = None
    bars_since_completion: int | None = None


class AnalysisResponse(BaseModel):
    symbol: str
    rank: int = 0
    scanned_at: str = ""  # ISO timestamp of when this analysis was cached
    composite_score: float = 0.0
    category_scores: CategoryScores = CategoryScores()
    profile_matches: list[str] = []
    signals: dict[str, float] = {}
    meta: AnalysisMeta | None = None
    harmonics: HarmonicInfo | None = None
    chart_patterns: list[PatternDetectionResponse] = []
    is_actionable: bool = False
    volume_contradiction: bool = False
    needs_scan: bool = False  # True for watchlist symbols with no cached analysis


class ScanRunResponse(BaseModel):
    run_id: int
    status: str
    symbols_queued: int


class ScanRunStatusResponse(BaseModel):
    run_id: int
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    error_message: str | None = None
    symbols_scanned: int = 0
    symbols_scored: int = 0


class ProfileInfo(BaseModel):
    name: str
    description: str
    score_threshold: float
    required_conditions: list[str]
