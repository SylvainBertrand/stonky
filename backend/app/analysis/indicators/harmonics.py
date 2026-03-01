"""
Harmonic pattern detection using pyharmonics.

Detects XABCD harmonic patterns (Gartley, Bat, Butterfly, Crab, Shark, Cypher, ABCD)
and exposes:
  - HarmonicMatch dataclass
  - detect_harmonics(df) -> list[HarmonicMatch]
  - compute_harmonics_signals(df, matches) -> dict[str, float]
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

MIN_BARS_HARMONICS = 100

# Pattern weight by priority tier
_PATTERN_WEIGHTS: dict[str, float] = {
    "gartley": 1.0,
    "bat": 1.0,
    "alt bat": 1.0,
    "butterfly": 0.85,
    "deep butterfly": 0.85,
    "crab": 0.85,
    "deep crab": 0.85,
    "bartley": 0.85,
    "shark": 0.7,
    "deep shark": 0.7,
    "cypher": 0.7,
}

# Display names for API (maps pyharmonics lowercase → user-facing name)
_DISPLAY_NAMES: dict[str, str] = {
    "gartley": "Gartley",
    "bat": "Bat",
    "alt bat": "Bat",
    "butterfly": "Butterfly",
    "deep butterfly": "Butterfly",
    "crab": "Crab",
    "deep crab": "Crab",
    "bartley": "Gartley",
    "shark": "Shark",
    "deep shark": "Shark",
    "cypher": "Cypher",
}


@dataclass
class HarmonicMatch:
    pattern_name: str          # e.g. "Gartley", "Bat"
    direction: str             # "bullish" or "bearish"
    completion_bar: int        # DataFrame bar index of point D
    bars_since_completion: int # how many bars since D completed
    prz_low: float             # Potential Reversal Zone lower bound
    prz_high: float            # PRZ upper bound
    ratio_quality: float       # 0.0–1.0, how tightly ratios match ideal values
    x: float                   # XABCD price points
    a: float
    b: float
    c: float
    d: float


def _compute_ratio_quality(pattern_name: str, retraces: dict[str, float]) -> float:
    """
    Compute ratio quality as 1 - mean(|measured - ideal| / ideal) across all legs.

    Uses ideal values from pyharmonics.constants.HARMONIC_PATTERNS. For legs with
    a min/max range, the ideal is the midpoint. If measured is within [min, max],
    error is 0; outside, error is distance to nearest bound divided by ideal.
    Clamped to [0, 1].
    """
    try:
        from pyharmonics import constants  # deferred to avoid import at module load
        xabcd_defs = constants.HARMONIC_PATTERNS.get("XABCD", {})
        ideal_def: dict[str, Any] = xabcd_defs.get(pattern_name, {})
    except Exception:
        return 0.5

    if not ideal_def:
        return 0.5

    errors: list[float] = []
    for leg, measured in retraces.items():
        if leg not in ideal_def:
            continue
        leg_def = ideal_def[leg]
        if not isinstance(leg_def, dict):
            continue
        lo = float(leg_def.get("min", measured))
        hi = float(leg_def.get("max", measured))
        ideal = (lo + hi) / 2.0
        if ideal <= 0:
            continue
        # If within range, error = 0; otherwise distance to nearest bound
        if lo <= measured <= hi:
            err = 0.0
        else:
            err = min(abs(measured - lo), abs(measured - hi)) / ideal
        errors.append(err)

    if not errors:
        return 0.5

    quality = 1.0 - sum(errors) / len(errors)
    return max(0.0, min(1.0, quality))


def detect_harmonics(
    df: pd.DataFrame,
    max_bars_since_completion: int = 10,
    min_ratio_quality: float = 0.7,
) -> list[HarmonicMatch]:
    """
    Run pyharmonics detection on df.

    Returns only patterns completed within `max_bars_since_completion` bars and
    with ratio_quality >= `min_ratio_quality`. Sorted by ratio_quality descending.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV with columns: open, high, low, close, volume.
    max_bars_since_completion : int
        Maximum bars since D-point to include. Filters out stale patterns.
    min_ratio_quality : float
        Minimum ratio quality score to include. Filters poor-quality matches.
    """
    if len(df) < MIN_BARS_HARMONICS:
        log.debug("Insufficient bars for harmonic detection: %d < %d", len(df), MIN_BARS_HARMONICS)
        return []

    try:
        from pyharmonics import OHLCTechnicals
        from pyharmonics.search.harmonic import HarmonicSearch

        # Build a clean DataFrame with only the columns pyharmonics needs.
        # Reset index so pattern.x[-1] is always an integer bar position.
        phdf = df[["open", "high", "low", "close", "volume"]].reset_index(drop=True)

        # peak_spacing=5: balances sensitivity vs noise for daily equity data
        t = OHLCTechnicals(phdf, "symbol", "1d", peak_spacing=5)
        h = HarmonicSearch(t, fib_tolerance=0.03)

        # Search only patterns whose D point falls in the last (max + 5) peaks
        h.search(limit_to=max_bars_since_completion + 5)

        all_patterns = h.get_patterns(family=h.XABCD)
        xabcd_list = all_patterns.get("XABCD", [])

        matches: list[HarmonicMatch] = []
        n = len(df)

        for pat in xabcd_list:
            name: str = pat.name  # lowercase, e.g. "gartley"

            # pat.x is a list of DataFrame index values for [X, A, B, C, D].
            # Since we reset_index, these are integers 0..n-1.
            if not pat.x or len(pat.x) < 5:
                continue

            d_bar = int(pat.x[-1])
            bars_since = n - 1 - d_bar

            if bars_since < 0 or bars_since > max_bars_since_completion:
                continue

            # PRZ bounds — pyharmonics provides them directly
            prz_low = float(min(pat.completion_min_price, pat.completion_max_price))
            prz_high = float(max(pat.completion_min_price, pat.completion_max_price))

            # Ratio quality from measured retraces vs ideal values
            retraces = {str(k): float(v) for k, v in pat.retraces.items()}
            quality = _compute_ratio_quality(name, retraces)

            if quality < min_ratio_quality:
                continue

            # y = [X, A, B, C, D] price values
            y = pat.y
            display_name = _DISPLAY_NAMES.get(name, name.title())

            matches.append(
                HarmonicMatch(
                    pattern_name=display_name,
                    direction="bullish" if pat.bullish else "bearish",
                    completion_bar=d_bar,
                    bars_since_completion=bars_since,
                    prz_low=prz_low,
                    prz_high=prz_high,
                    ratio_quality=quality,
                    x=float(y[0]),
                    a=float(y[1]),
                    b=float(y[2]),
                    c=float(y[3]),
                    d=float(y[4]),
                )
            )

        matches.sort(key=lambda m: m.ratio_quality, reverse=True)
        return matches

    except Exception as exc:
        log.warning("Harmonic detection failed: %s", exc, exc_info=True)
        return []


def compute_harmonics_signals(
    df: pd.DataFrame,
    matches: list[HarmonicMatch],
) -> dict[str, float]:
    """
    Normalize harmonic match results into a float signal dict.

    Returns
    -------
    dict with keys:
        harmonic_score           : float [-1.0, +1.0]
        harmonic_pattern_detected: float  1.0 if detected, 0.0 otherwise
        harmonic_in_prz          : float  1.0 if current close inside PRZ, 0.0 otherwise
        harmonic_ratio_quality   : float [0.0, 1.0]
    """
    if not matches:
        return {
            "harmonic_score": 0.0,
            "harmonic_pattern_detected": 0.0,
            "harmonic_in_prz": 0.0,
            "harmonic_ratio_quality": 0.0,
        }

    best = matches[0]  # already sorted by ratio_quality descending
    current_close = float(df["close"].iloc[-1]) if not df.empty else 0.0

    # Pattern weight
    name_lower = best.pattern_name.lower()
    pattern_weight = _PATTERN_WEIGHTS.get(name_lower, 0.7)

    # Recency weight: linear decay from 1.0 (bars_since=0) to 0.0 (bars_since=10)
    max_bars = 10
    recency_weight = max(0.0, 1.0 - best.bars_since_completion / max_bars)

    # Raw magnitude
    magnitude = best.ratio_quality * pattern_weight * recency_weight

    # PRZ bonus: multiply by 1.2 if price is inside PRZ (cap at 1.0)
    in_prz = best.prz_low <= current_close <= best.prz_high
    if in_prz:
        magnitude = min(1.0, magnitude * 1.2)

    # Direction
    score = magnitude if best.direction == "bullish" else -magnitude
    score = max(-1.0, min(1.0, score))

    return {
        "harmonic_score": score,
        "harmonic_pattern_detected": 1.0,
        "harmonic_in_prz": 1.0 if in_prz else 0.0,
        "harmonic_ratio_quality": best.ratio_quality,
    }
