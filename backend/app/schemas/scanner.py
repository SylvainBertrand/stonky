"""
Pydantic schemas for the scanner API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


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
    timestamp: str
    bars: int = 0


class AnalysisResponse(BaseModel):
    symbol: str
    composite_score: float
    category_scores: CategoryScores
    profile_matches: list[str]
    signals: dict[str, float]
    meta: AnalysisMeta


class ScanRunResponse(BaseModel):
    run_id: str
    status: str
    symbols_scanned: int
    results: list[AnalysisResponse]


class ProfileInfo(BaseModel):
    name: str
    description: str
    score_threshold: float
    required_conditions: list[str]
