"""Elliott Wave detection — hybrid greedy + Fibonacci-ratio algorithm.

Detects 5-wave impulse and 3-wave corrective (A-B-C) structures using
existing swing point infrastructure. Runs inline in the analysis pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd  # noqa: F401  # used by detect_elliott_waves (added in next task)

# ── Data types ────────────────────────────────────────────────────────────────


@dataclass
class WavePoint:
    time: str
    price: float
    label: str  # "0","1","2","3","4","5" or "0","A","B","C"
    bar_index: int


@dataclass
class WaveSequence:
    wave_type: Literal["impulse", "corrective"]
    direction: Literal["bullish", "bearish"]
    waves: list[WavePoint]  # 6 pts for impulse, 4 for corrective
    confidence: float  # 0–1


@dataclass
class EWResult:
    best_wave: WaveSequence | None = None
    current_position: str | None = None  # "wave_3", "wave_5", "wave_A", etc.
    confidence: float = 0.0


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fib_score(actual_ratio: float, target: float, tolerance: float = 0.25) -> float:
    """Score how close actual_ratio is to a Fibonacci target. Returns 0–1."""
    diff = abs(actual_ratio - target) / max(target, 1e-9)
    if diff >= tolerance:
        return 0.0
    return 1.0 - (diff / tolerance)


def _impulse_confidence(prices: list[float]) -> float:
    """Score Fibonacci ratio quality for a 6-point impulse sequence."""
    p = prices
    amp1 = abs(p[1] - p[0])
    amp2 = abs(p[2] - p[1])
    amp3 = abs(p[3] - p[2])
    amp4 = abs(p[4] - p[3])
    amp5 = abs(p[5] - p[4])
    if amp1 == 0:
        return 0.0
    scores = [
        _fib_score(amp2 / amp1, 0.618),  # W2 retraces 61.8% of W1
        _fib_score(amp3 / amp1, 1.618),  # W3 = 161.8% of W1
        _fib_score(amp4 / amp3, 0.382) if amp3 > 0 else 0.0,  # W4 retraces 38.2% of W3
        _fib_score(amp5 / amp1, 1.0),  # W5 = 100% of W1
    ]
    return float(np.mean(scores))


def _check_impulse_rules(prices: list[float], direction: Literal["bullish", "bearish"]) -> bool:
    """Validate core Elliott Wave impulse rules."""
    p0, p1, p2, p3, p4, p5 = prices

    if direction == "bullish":
        if not (p1 > p0 and p2 < p1 and p3 > p2 and p4 < p3 and p5 > p4):
            return False
        if p2 <= p0:  # W2 never below W0
            return False
        if p4 <= p1:  # W4 never below W1 (no overlap)
            return False
        amp1 = p1 - p0
        amp3 = p3 - p2
        amp5 = p5 - p4
    else:  # bearish
        if not (p1 < p0 and p2 > p1 and p3 < p2 and p4 > p3 and p5 < p4):
            return False
        if p2 >= p0:
            return False
        if p4 >= p1:
            return False
        amp1 = p0 - p1
        amp3 = p2 - p3
        amp5 = p4 - p5

    # Wave 3 must not be the shortest
    if amp3 < amp1 and amp3 < amp5:
        return False

    return True


def _corrective_confidence(prices: list[float]) -> float:
    """Score Fibonacci ratio quality for a 4-point corrective (A-B-C) sequence."""
    p = prices
    amp_a = abs(p[1] - p[0])
    amp_b = abs(p[2] - p[1])
    amp_c = abs(p[3] - p[2])
    if amp_a == 0:
        return 0.0
    scores = [
        _fib_score(amp_b / amp_a, 0.618),  # B retraces 61.8% of A
        _fib_score(amp_c / amp_a, 1.0),  # C = A
    ]
    return float(np.mean(scores))


# ── Main detection function ────────────────────────────────────────────────────


def detect_elliott_waves(
    df: pd.DataFrame,
    swing_high_idx: np.ndarray,
    swing_low_idx: np.ndarray,
    lookback_bars: int = 120,
) -> EWResult:
    """Detect Elliott Wave patterns using pre-computed swing point indices.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV DataFrame with 'time', 'high', 'low' columns.
    swing_high_idx : np.ndarray
        Integer indices of swing highs in df.
    swing_low_idx : np.ndarray
        Integer indices of swing lows in df.
    lookback_bars : int
        Only consider pivots in the last N bars.

    Returns
    -------
    EWResult with the best wave found (or empty result if none).
    """
    if len(swing_high_idx) < 3 or len(swing_low_idx) < 3:
        return EWResult()

    last_bar = len(df) - 1
    start_bar = max(0, last_bar - lookback_bars)

    times = df["time"].tolist() if "time" in df.columns else [str(i) for i in range(len(df))]
    highs_col = df["high"].to_numpy()
    lows_col = df["low"].to_numpy()

    # Build pivot list: (bar_index, price, time_str, kind)
    pivots: list[tuple[int, float, str, str]] = []
    for i in swing_high_idx:
        if int(i) >= start_bar:
            pivots.append((int(i), float(highs_col[i]), str(times[i]), "high"))
    for i in swing_low_idx:
        if int(i) >= start_bar:
            pivots.append((int(i), float(lows_col[i]), str(times[i]), "low"))
    pivots.sort(key=lambda x: x[0])

    if len(pivots) < 4:
        return EWResult()

    best: WaveSequence | None = None

    # Scan for 5-wave impulse (6 consecutive alternating pivots)
    if len(pivots) >= 6:
        for start in range(len(pivots) - 5):
            window = pivots[start : start + 6]
            prices = [pt[1] for pt in window]
            kinds = [pt[3] for pt in window]

            direction: Literal["bullish", "bearish"] | None = None
            if kinds == ["low", "high", "low", "high", "low", "high"]:
                direction = "bullish"
            elif kinds == ["high", "low", "high", "low", "high", "low"]:
                direction = "bearish"

            if direction and _check_impulse_rules(prices, direction):
                conf = _impulse_confidence(prices)
                if best is None or conf > best.confidence:
                    wave_points = [
                        WavePoint(
                            time=window[i][2],
                            price=window[i][1],
                            label=str(i),
                            bar_index=window[i][0],
                        )
                        for i in range(6)
                    ]
                    best = WaveSequence("impulse", direction, wave_points, conf)

    # Scan for 3-wave corrective (4 consecutive alternating pivots)
    for start in range(len(pivots) - 3):
        window = pivots[start : start + 4]
        prices = [pt[1] for pt in window]
        kinds = [pt[3] for pt in window]

        corr_dir: Literal["bullish", "bearish"] | None = None
        if (
            kinds == ["high", "low", "high", "low"]
            and prices[1] < prices[0]
            and prices[2] > prices[1]
            and prices[3] < prices[2]
        ):
            corr_dir = "bearish"
        elif (
            kinds == ["low", "high", "low", "high"]
            and prices[1] > prices[0]
            and prices[2] < prices[1]
            and prices[3] > prices[2]
        ):
            corr_dir = "bullish"

        if corr_dir is not None:
            conf = _corrective_confidence(prices) * 0.7  # discount vs impulse
            if best is None or conf > best.confidence:
                labels = ["0", "A", "B", "C"]
                wave_points = [
                    WavePoint(
                        time=window[i][2],
                        price=window[i][1],
                        label=labels[i],
                        bar_index=window[i][0],
                    )
                    for i in range(4)
                ]
                best = WaveSequence("corrective", corr_dir, wave_points, conf)

    if best is None:
        return EWResult()

    current_pos = _determine_current_position(best, last_bar)
    return EWResult(best_wave=best, current_position=current_pos, confidence=best.confidence)


def _determine_current_position(wave: WaveSequence, last_bar: int) -> str | None:
    """Determine which wave segment the last bar falls in."""
    waves = wave.waves
    for i in range(len(waves) - 1):
        if waves[i].bar_index <= last_bar <= waves[i + 1].bar_index:
            if wave.wave_type == "impulse":
                return f"wave_{i + 1}"
            else:
                labels = ["A", "B", "C"]
                if i < len(labels):
                    return f"wave_{labels[i]}"
    if last_bar > waves[-1].bar_index:
        return "wave_5_complete" if wave.wave_type == "impulse" else "wave_C_complete"
    return None


# ── Signal computation ─────────────────────────────────────────────────────────


def compute_ew_signals(result: EWResult) -> dict[str, float]:
    """Convert EWResult into normalized signals for the pipeline scoring.

    Returns signals in [-1, 1] range compatible with the scoring engine.
    """
    signals: dict[str, float] = {"ew_ratio_quality": result.confidence}
    pos = result.current_position
    if pos is None or result.best_wave is None:
        signals["ew_wave3_active"] = 0.0
        signals["ew_wave5_active"] = 0.0
        signals["ew_corrective_abc"] = 0.0
        return signals
    signals["ew_wave3_active"] = 1.0 if pos == "wave_3" else 0.0
    signals["ew_wave5_active"] = 0.5 if pos == "wave_5" else 0.0
    signals["ew_corrective_abc"] = -0.3 if result.best_wave.wave_type == "corrective" else 0.0
    return signals
