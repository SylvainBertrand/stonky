"""Pydantic v2 request/response schemas for the TA Pre-Scorer endpoint.

POST /api/ta/prescore — pre-scores tickers for the TA Intraday Claude agent.

Reference: TC-SWE-95 Phase 1 design document.
Schema version: 1.0.0
"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Request
# ---------------------------------------------------------------------------


class PrescoreRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=100)
    score_threshold: float = Field(default=4.5, ge=0.0, le=10.0)
    dedup_lookback_hours: int = Field(default=24, ge=1, le=168)


# ---------------------------------------------------------------------------
# Response — nested models
# ---------------------------------------------------------------------------


class TrendIndicators(BaseModel):
    ma50: float | None = None
    ma200: float | None = None
    ma_cross_state: str = "none"
    raw_score: float = 0.0


class MomentumIndicators(BaseModel):
    rsi14: float | None = None
    macd_hist: float | None = None
    raw_score: float = 0.0


class VolatilityIndicators(BaseModel):
    atr14_pct: float | None = None
    bb_width_pct: float | None = None
    raw_score: float = 0.0


class VolumeIndicators(BaseModel):
    vol_ratio_5d: float | None = None
    raw_score: float = 0.0


class IndicatorBreakdown(BaseModel):
    trend: TrendIndicators = Field(default_factory=TrendIndicators)
    momentum: MomentumIndicators = Field(default_factory=MomentumIndicators)
    volatility: VolatilityIndicators = Field(default_factory=VolatilityIndicators)
    volume: VolumeIndicators = Field(default_factory=VolumeIndicators)


class CandidateLevels(BaseModel):
    entry: float
    stop: float
    target: float
    r_multiple: float
    stop_basis: str
    target_basis: str


class DedupStatus(BaseModel):
    registry_match_url: str | None = None
    registry_match_score: float | None = None
    filing_recommended: bool = True
    skip_reason: str | None = None
    notes_for_claude: str | None = None


class ScoredTicker(BaseModel):
    ticker: str
    indicators: IndicatorBreakdown
    composite_score: float
    pattern_signature: str
    candidate_levels: CandidateLevels | None = None
    dedup_status: DedupStatus = Field(default_factory=DedupStatus)
    notes_for_claude: list[str] = Field(default_factory=list)


class FilteredTicker(BaseModel):
    ticker: str
    reason: str


class PrescoreMetadata(BaseModel):
    tickers_input: int
    tickers_scored: int
    tickers_above_threshold: int
    tickers_filtered_dedup: int
    stonky_pipeline_latency_ms: int
    # TC-SWE-102: Diagnostic fields for screener-universe debugging
    symbols_resolved: int = 0
    filter_reasons: dict[str, int] = Field(default_factory=dict)
    backfill_stats: dict[str, int] = Field(default_factory=dict)


class HydrateRequest(BaseModel):
    """Request body for the async pre-warm endpoint."""

    tickers: list[str] = Field(..., min_length=1, max_length=200)


class HydrateResponse(BaseModel):
    """Immediate acknowledgement from the hydrate endpoint."""

    status: str = "queued"
    tickers_submitted: int


class PrescoreResponse(BaseModel):
    schema_version: str = "1.0.0"
    scan_timestamp: str
    tickers: list[ScoredTicker] = Field(default_factory=list)
    filtered_out: list[FilteredTicker] = Field(default_factory=list)
    metadata: PrescoreMetadata
