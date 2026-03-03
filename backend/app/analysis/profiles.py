"""
Scanner profiles: 4 concrete strategy profiles that filter analysis results.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class ProfileResult:
    name: str
    matches: bool
    conditions_met: dict[str, bool]


class ScannerProfile(Protocol):
    name: str
    description: str
    score_threshold: float

    def check(
        self,
        signals: dict[str, float],
        category_scores: dict[str, float],
        composite: float,
    ) -> ProfileResult: ...


# ---------------------------------------------------------------------------
# MomentumBreakout
# ---------------------------------------------------------------------------

@dataclass
class MomentumBreakout:
    name: str = "MomentumBreakout"
    description: str = (
        "Stocks breaking out of consolidation with expanding momentum. "
        "Requires strong trend + positive momentum + volume confirmation."
    )
    score_threshold: float = 0.2
    required_conditions: list[str] = field(default_factory=lambda: [
        "trend_bullish",
        "momentum_positive",
        "volume_positive",
        "adx_trending",
    ])

    def check(
        self,
        signals: dict[str, float],
        category_scores: dict[str, float],
        composite: float,
    ) -> ProfileResult:
        conditions: dict[str, bool] = {
            "trend_bullish": category_scores.get("trend", 0.0) > 0.3,
            "momentum_positive": category_scores.get("momentum", 0.0) > 0.0,
            "volume_positive": category_scores.get("volume", 0.0) > 0.0,
            # ADX-based trend strength (adx_dmi > 0.1 ≈ ADX > ~20)
            "adx_trending": signals.get("adx_dmi", 0.0) > 0.1,
        }
        matches = composite >= self.score_threshold and all(conditions.values())
        return ProfileResult(name=self.name, matches=matches, conditions_met=conditions)


# ---------------------------------------------------------------------------
# MeanReversion
# ---------------------------------------------------------------------------

@dataclass
class MeanReversion:
    name: str = "MeanReversion"
    description: str = (
        "Oversold stocks near support with divergence signals. "
        "Requires oversold oscillators + S/R support + bullish divergence."
    )
    score_threshold: float = 0.1
    required_conditions: list[str] = field(default_factory=lambda: [
        "oversold_or_divergence",
        "stochastic_oversold",
        "near_support",
    ])

    def check(
        self,
        signals: dict[str, float],
        category_scores: dict[str, float],
        composite: float,
    ) -> ProfileResult:
        conditions: dict[str, bool] = {
            # RSI<35 (signal ~> 0.2) OR any bullish divergence (RSI or MACD)
            "oversold_or_divergence": (
                signals.get("rsi", 0.0) > 0.2
                or signals.get("rsi_divergence", 0.0) > 0.0
                or signals.get("macd_divergence", 0.0) > 0.0
            ),
            # Stochastic in oversold territory (signal > 0.15 ≈ %K < 30)
            "stochastic_oversold": signals.get("stochastic", 0.0) > 0.15,
            # Price near support (Fib or Pivot) OR at lower Bollinger Band
            "near_support": (
                category_scores.get("support_resistance", 0.0) > 0.0
                or signals.get("bb_pct_b", 0.0) > 0.3
            ),
        }
        matches = composite >= self.score_threshold and all(conditions.values())
        return ProfileResult(name=self.name, matches=matches, conditions_met=conditions)


# ---------------------------------------------------------------------------
# TrendFollowing
# ---------------------------------------------------------------------------

@dataclass
class TrendFollowing:
    name: str = "TrendFollowing"
    description: str = (
        "Strong trending stocks with EMA alignment. "
        "Requires bullish EMA stack + ADX strength + Supertrend confirmation."
    )
    score_threshold: float = 0.25
    required_conditions: list[str] = field(default_factory=lambda: [
        "ema_stack_bullish",
        "adx_trending",
        "supertrend_bullish",
        "rsi_in_range",
        "obv_rising",
    ])

    def check(
        self,
        signals: dict[str, float],
        category_scores: dict[str, float],
        composite: float,
    ) -> ProfileResult:
        conditions: dict[str, bool] = {
            "ema_stack_bullish": signals.get("ema_stack", 0.0) > 0.3,
            "adx_trending": signals.get("adx_dmi", 0.0) > 0.25,
            "supertrend_bullish": signals.get("supertrend", 0.0) > 0.0,
            # RSI 40–65: signal between ~+0.1 and ~-0.25 (not extreme in either direction)
            "rsi_in_range": -0.3 < signals.get("rsi", 0.0) < 0.5,
            # OBV trending up
            "obv_rising": signals.get("obv", 0.0) > 0.0,
        }
        matches = composite >= self.score_threshold and all(conditions.values())
        return ProfileResult(name=self.name, matches=matches, conditions_met=conditions)


# ---------------------------------------------------------------------------
# HarmonicSetup — wired to real pyharmonics detection
# ---------------------------------------------------------------------------

@dataclass
class HarmonicSetup:
    name: str = "HarmonicSetup"
    description: str = (
        "Harmonic XABCD pattern completions near their Potential Reversal Zone. "
        "Requires a detected pattern (ratio_quality >= 0.75) plus RSI or MACD divergence."
    )
    score_threshold: float = -1.0
    required_conditions: list[str] = field(default_factory=lambda: [
        "harmonic_pattern_detected",
        "harmonic_quality",
        "rsi_or_macd_divergence",
    ])

    def check(
        self,
        signals: dict[str, float],
        category_scores: dict[str, float],
        composite: float,
    ) -> ProfileResult:
        conditions: dict[str, bool] = {
            "harmonic_pattern_detected": signals.get("harmonic_pattern_detected", 0.0) > 0.5,
            "harmonic_quality": signals.get("harmonic_ratio_quality", 0.0) >= 0.75,
            # Any RSI or MACD divergence signal present (positive = bullish, negative = bearish)
            "rsi_or_macd_divergence": (
                signals.get("rsi_divergence", 0.0) != 0.0
                or signals.get("macd_divergence", 0.0) != 0.0
            ),
        }
        matches = composite >= self.score_threshold and all(conditions.values())
        return ProfileResult(name=self.name, matches=matches, conditions_met=conditions)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

PROFILES: dict[str, ScannerProfile] = {
    "MomentumBreakout": MomentumBreakout(),  # type: ignore[dict-item]
    "MeanReversion": MeanReversion(),  # type: ignore[dict-item]
    "TrendFollowing": TrendFollowing(),  # type: ignore[dict-item]
    "HarmonicSetup": HarmonicSetup(),  # type: ignore[dict-item]
}


def evaluate_profiles(
    signals: dict[str, float],
    category_scores: dict[str, float],
    composite: float,
) -> list[str]:
    """Run all profiles and return list of matching profile names."""
    return [
        name
        for name, profile in PROFILES.items()
        if profile.check(signals, category_scores, composite).matches
    ]
