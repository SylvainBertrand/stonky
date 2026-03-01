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
    score_threshold: float = 0.4
    required_conditions: list[str] = field(default_factory=lambda: [
        "trend_bullish",
        "momentum_positive",
        "volume_positive",
        "ttm_squeeze_fired",
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
            "ttm_squeeze_fired": signals.get("ttm_squeeze", 0.0) >= 0.9,
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
    score_threshold: float = 0.2
    required_conditions: list[str] = field(default_factory=lambda: [
        "oversold",
        "near_support",
        "bullish_divergence",
    ])

    def check(
        self,
        signals: dict[str, float],
        category_scores: dict[str, float],
        composite: float,
    ) -> ProfileResult:
        conditions: dict[str, bool] = {
            "oversold": signals.get("rsi", 0.0) > 0.5,
            "near_support": category_scores.get("support_resistance", 0.0) > 0.0,
            "bullish_divergence": category_scores.get("divergence", 0.0) > 0.0,
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
    score_threshold: float = 0.35
    required_conditions: list[str] = field(default_factory=lambda: [
        "ema_stack_bullish",
        "adx_trending",
        "supertrend_bullish",
    ])

    def check(
        self,
        signals: dict[str, float],
        category_scores: dict[str, float],
        composite: float,
    ) -> ProfileResult:
        conditions: dict[str, bool] = {
            "ema_stack_bullish": signals.get("ema_stack", 0.0) > 0.3,
            "adx_trending": signals.get("adx_dmi", 0.0) > 0.3,
            "supertrend_bullish": signals.get("supertrend", 0.0) > 0.0,
        }
        matches = composite >= self.score_threshold and all(conditions.values())
        return ProfileResult(name=self.name, matches=matches, conditions_met=conditions)


# ---------------------------------------------------------------------------
# HarmonicSetup (placeholder — harmonic detection not yet implemented)
# ---------------------------------------------------------------------------

@dataclass
class HarmonicSetup:
    name: str = "HarmonicSetup"
    description: str = (
        "Harmonic XABCD pattern completions (placeholder). "
        "Always returns False until pyharmonics integration is complete."
    )
    score_threshold: float = 0.3
    required_conditions: list[str] = field(default_factory=lambda: [
        "harmonic_pattern_detected",
    ])

    def check(
        self,
        signals: dict[str, float],
        category_scores: dict[str, float],
        composite: float,
    ) -> ProfileResult:
        conditions: dict[str, bool] = {
            "harmonic_pattern_detected": False,  # placeholder
        }
        return ProfileResult(name=self.name, matches=False, conditions_met=conditions)


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
