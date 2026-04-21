"""TA Pre-Scorer service — deterministic scoring for the TA Intraday agent.

Reuses the existing analysis pipeline and remaps to 4-category TA weights.
Pattern classification, candidate levels, dedup, and notes generation.

Reference: TC-SWE-95 Phase 1 design document.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

from app.analysis.indicators.momentum import compute_macd, compute_rsi
from app.analysis.indicators.trend import compute_ema
from app.analysis.indicators.volatility import compute_bbands
from app.analysis.pipeline import AnalysisResult
from app.schemas.ta import (
    CandidateLevels,
    DedupStatus,
    IndicatorBreakdown,
    MomentumIndicators,
    ScoredTicker,
    TrendIndicators,
    VolatilityIndicators,
    VolumeIndicators,
)

log = logging.getLogger(__name__)

# TA Intraday 4-category weights (ticket spec)
TA_WEIGHTS = {"trend": 0.4, "momentum": 0.3, "volatility": 0.2, "volume": 0.1}

# Pattern signature priority (highest priority first, mutually exclusive)
PATTERN_SIGNATURES = [
    "breakout",
    "mean_reversion",
    "uptrend_continuation",
    "consolidation",
    "chop",
]


# ---------------------------------------------------------------------------
# Score remapping: pipeline [-1, +1] → TA [0, 10]
# ---------------------------------------------------------------------------


def remap_score(pipeline_score: float) -> float:
    """Map a pipeline score from [-1, +1] to [0, 10]."""
    return round((pipeline_score + 1.0) * 5.0, 2)


def compute_ta_composite(category_scores: dict[str, float]) -> float:
    """Compute 4-category TA composite on [0, 10] scale."""
    trend = remap_score(category_scores.get("trend", 0.0))
    momentum = remap_score(category_scores.get("momentum", 0.0))
    volatility = remap_score(category_scores.get("volatility", 0.0))
    volume = remap_score(category_scores.get("volume", 0.0))
    return round(
        TA_WEIGHTS["trend"] * trend
        + TA_WEIGHTS["momentum"] * momentum
        + TA_WEIGHTS["volatility"] * volatility
        + TA_WEIGHTS["volume"] * volume,
        2,
    )


# ---------------------------------------------------------------------------
# Raw indicator extraction
# ---------------------------------------------------------------------------


def extract_raw_indicators(df: pd.DataFrame) -> dict[str, Any]:
    """Extract raw (non-normalized) indicator values from OHLCV DataFrame.

    Returns dict with keys: ma50, ma200, rsi14, macd_hist, atr14_pct,
    bb_width_pct, vol_ratio_5d, ma_cross_state.
    """
    raw: dict[str, Any] = {}

    # EMAs
    try:
        d = compute_ema(df)
        ma50 = d["ema_50"].dropna()
        ma200 = d["ema_200"].dropna()
        raw["ma50"] = round(float(ma50.iloc[-1]), 2) if not ma50.empty else None
        raw["ma200"] = round(float(ma200.iloc[-1]), 2) if not ma200.empty else None
        if raw["ma50"] is not None and raw["ma200"] is not None:
            if raw["ma50"] > raw["ma200"]:
                raw["ma_cross_state"] = "golden"
            elif raw["ma50"] < raw["ma200"]:
                raw["ma_cross_state"] = "death"
            else:
                raw["ma_cross_state"] = "none"
        else:
            raw["ma_cross_state"] = "none"
    except Exception:
        raw.update({"ma50": None, "ma200": None, "ma_cross_state": "none"})

    # RSI
    try:
        d = compute_rsi(df)
        rsi_vals = d["rsi_14"].dropna()
        raw["rsi14"] = round(float(rsi_vals.iloc[-1]), 1) if not rsi_vals.empty else None
    except Exception:
        raw["rsi14"] = None

    # MACD histogram
    try:
        d = compute_macd(df)
        hist = d.get("macdh", pd.Series(dtype=float))
        if isinstance(hist, pd.Series):
            hist_clean = hist.dropna()
            raw["macd_hist"] = (
                round(float(hist_clean.iloc[-1]), 4) if not hist_clean.empty else None
            )
        else:
            raw["macd_hist"] = None
    except Exception:
        raw["macd_hist"] = None

    # ATR pct (from last 14 bars)
    try:
        import pandas_ta as pta

        atr_s = pta.atr(df["high"], df["low"], df["close"], length=14)
        if atr_s is not None:
            atr_clean = atr_s.dropna()
            if not atr_clean.empty:
                atr_val = float(atr_clean.iloc[-1])
                last_price = float(df["close"].iloc[-1])
                raw["atr14_pct"] = (
                    round(atr_val / last_price * 100.0, 2) if last_price > 0 else None
                )
            else:
                raw["atr14_pct"] = None
        else:
            raw["atr14_pct"] = None
    except Exception:
        raw["atr14_pct"] = None

    # Bollinger Band width %
    try:
        d = compute_bbands(df)
        bbu = d.get("bbu", pd.Series(dtype=float))
        bbl = d.get("bbl", pd.Series(dtype=float))
        bbm = d.get("bbm", pd.Series(dtype=float))
        if isinstance(bbu, pd.Series) and isinstance(bbl, pd.Series) and isinstance(bbm, pd.Series):
            bbu_v = bbu.dropna()
            bbl_v = bbl.dropna()
            bbm_v = bbm.dropna()
            if not bbu_v.empty and not bbl_v.empty and not bbm_v.empty:
                mid = float(bbm_v.iloc[-1])
                width = float(bbu_v.iloc[-1]) - float(bbl_v.iloc[-1])
                raw["bb_width_pct"] = round(width / mid * 100.0, 2) if mid > 0 else None
            else:
                raw["bb_width_pct"] = None
        else:
            raw["bb_width_pct"] = None
    except Exception:
        raw["bb_width_pct"] = None

    # Volume ratio (5-day)
    try:
        vol = df["volume"].astype(float)
        avg_vol = vol.rolling(5).mean().iloc[-1]
        raw["vol_ratio_5d"] = (
            round(float(vol.iloc[-1]) / float(avg_vol), 2) if avg_vol > 0 else None
        )
    except Exception:
        raw["vol_ratio_5d"] = None

    return raw


# ---------------------------------------------------------------------------
# Pattern signature classifier
# ---------------------------------------------------------------------------


def classify_pattern(
    signals: dict[str, float],
    category_scores: dict[str, float],
    ta_composite: float,
) -> str:
    """Deterministic pattern classification with strict precedence.

    Priority order (first match wins):
    1. breakout — strong ADX + volume expansion + mid-to-high composite
    2. mean_reversion — oversold RSI + near support + low-to-mid composite
    3. uptrend_continuation — bullish EMA stack + supertrend + high composite
    4. consolidation — low ADX + narrow composite range
    5. chop — default
    """
    ema_stack = signals.get("ema_stack", 0.0)
    adx_dmi = signals.get("adx_dmi", 0.0)
    supertrend = signals.get("supertrend", 0.0)
    rsi = signals.get("rsi", 0.0)
    bb_pct_b = signals.get("bb_pct_b", 0.0)
    vol_score = category_scores.get("volume", 0.0)

    # 1. Breakout: strong directional momentum with volume confirmation
    if abs(adx_dmi) > 0.25 and vol_score > 0.1 and ta_composite > 5.5:
        return "breakout"

    # 2. Mean reversion: oversold + near support
    if rsi > 0.2 and bb_pct_b > 0.2 and ta_composite < 6.0:
        return "mean_reversion"

    # 3. Uptrend continuation: aligned trend indicators + bullish
    if ema_stack > 0.3 and supertrend > 0 and ta_composite > 6.0:
        return "uptrend_continuation"

    # 4. Consolidation: low trend strength, neutral composite
    if abs(adx_dmi) < 0.15 and 3.5 < ta_composite < 6.5:
        return "consolidation"

    # 5. Chop: default
    return "chop"


# ---------------------------------------------------------------------------
# Candidate technical levels
# ---------------------------------------------------------------------------


def compute_candidate_levels(
    meta: dict[str, Any],
    ta_composite: float,
) -> CandidateLevels | None:
    """Compute entry/stop/target levels using ATR.

    Returns None if composite is in the neutral band [4.0, 6.0] (no clear direction).
    """
    last_price = meta.get("last_price", 0.0)
    atr = meta.get("atr", 0.0)

    if last_price <= 0 or atr <= 0:
        return None

    # Neutral band — no directional candidate
    if 4.0 <= ta_composite <= 6.0:
        return None

    is_long = ta_composite > 6.0
    stop_distance = atr * 2.0
    min_r_multiple = 1.5

    if is_long:
        entry = round(last_price, 2)
        stop = round(last_price - stop_distance, 2)
        target = round(last_price + stop_distance * min_r_multiple, 2)
        return CandidateLevels(
            entry=entry,
            stop=stop,
            target=target,
            r_multiple=min_r_multiple,
            stop_basis="atr_2x_below_entry",
            target_basis="1.5R_minimum_above_entry",
        )
    else:
        entry = round(last_price, 2)
        stop = round(last_price + stop_distance, 2)
        target = round(last_price - stop_distance * min_r_multiple, 2)
        return CandidateLevels(
            entry=entry,
            stop=stop,
            target=target,
            r_multiple=min_r_multiple,
            stop_basis="atr_2x_above_entry",
            target_basis="1.5R_minimum_below_entry",
        )


# ---------------------------------------------------------------------------
# Dedup check (Signal Registry via Notion API)
# ---------------------------------------------------------------------------


async def batch_dedup_check(
    tickers: list[str],
    lookback_hours: int,
) -> dict[str, DedupStatus]:
    """Query Signal Registry once for all tickers in the lookback window.

    Returns a dict mapping ticker → DedupStatus.
    """
    from app.agents_common.notion_client import (
        SIGNAL_REGISTRY_DB,
        _get_client,
        _page_url,
        _read_number,
        _read_title,
    )

    cutoff = (datetime.now(UTC) - timedelta(hours=lookback_hours)).isoformat()

    try:
        client = _get_client()
        response = await client.request(
            path=f"databases/{SIGNAL_REGISTRY_DB}/query",
            method="POST",
            body={
                "filter": {
                    "and": [
                        {"property": "Agent", "rich_text": {"equals": "technical-analyst"}},
                        {"property": "Date", "date": {"on_or_after": cutoff}},
                    ]
                },
                "sorts": [{"property": "Date", "direction": "descending"}],
            },
        )
        existing_signals = response.get("results", [])
    except Exception as exc:
        log.warning("Dedup query failed, defaulting to filing_recommended=true: %s", exc)
        return {t: DedupStatus() for t in tickers}

    # Index by ticker (keep most recent per ticker)
    by_ticker: dict[str, dict[str, Any]] = {}
    for page in existing_signals:
        ticker = _read_title(page, "Ticker")
        if ticker and ticker not in by_ticker:
            by_ticker[ticker] = {
                "url": _page_url(page),
                "score": _read_number(page, "Score"),
            }

    result: dict[str, DedupStatus] = {}
    for t in tickers:
        if t not in by_ticker:
            result[t] = DedupStatus(filing_recommended=True)
        else:
            existing = by_ticker[t]
            result[t] = DedupStatus(
                registry_match_url=existing["url"],
                registry_match_score=existing["score"],
                # Score comparison deferred — needs the new composite score.
                # Caller must finalize filing_recommended after computing TA composite.
                filing_recommended=True,
            )
    return result


def finalize_dedup(
    dedup: DedupStatus,
    new_composite: float,
) -> DedupStatus:
    """Apply score-delta rules to finalize dedup recommendation.

    Rules:
    - No existing signal → filing_recommended: true
    - Existing + delta ≤ 1.0 → filing_recommended: false, skip_reason set
    - Existing + delta > 1.0 → filing_recommended: true, notes_for_claude flags it
    """
    if dedup.registry_match_url is None:
        return dedup

    existing_score = dedup.registry_match_score or 0.0
    delta = abs(new_composite - existing_score)

    if delta <= 1.0:
        return DedupStatus(
            registry_match_url=dedup.registry_match_url,
            registry_match_score=existing_score,
            filing_recommended=False,
            skip_reason=(
                f"dedup: existing signal {dedup.registry_match_url} "
                f"score {existing_score:.1f}, delta {delta:.1f}"
            ),
        )
    else:
        return DedupStatus(
            registry_match_url=dedup.registry_match_url,
            registry_match_score=existing_score,
            filing_recommended=True,
            notes_for_claude=(
                f"previous signal {dedup.registry_match_url} score {existing_score:.1f}; "
                f"consider mark-superseded vs file-new"
            ),
        )


# ---------------------------------------------------------------------------
# Notes for Claude generation
# ---------------------------------------------------------------------------


def generate_notes(
    df: pd.DataFrame,
    raw_indicators: dict[str, Any],
    result: AnalysisResult,
    dedup: DedupStatus,
) -> list[str]:
    """Generate contextual annotations for Claude's judgment."""
    notes: list[str] = []

    # Stale data warning
    if "time" in df.columns and len(df) > 0:
        latest_bar = pd.Timestamp(df["time"].iloc[-1])
        if latest_bar.tzinfo is None:
            latest_bar = latest_bar.tz_localize("UTC")
        now = pd.Timestamp.now("UTC")
        age_minutes = (now - latest_bar).total_seconds() / 60.0
        if age_minutes > 30:
            hours = age_minutes / 60.0
            notes.append(f"Stale data: latest bar is {hours:.1f}h old")

    # Gappy bars (missing bars in last 100)
    if "time" in df.columns and len(df) >= 10:
        recent = df["time"].iloc[-min(100, len(df)) :]
        if len(recent) > 1:
            times = pd.to_datetime(recent)
            diffs = times.diff().dropna()
            if len(diffs) > 0:
                median_diff = diffs.median()
                # A gap is >2x the median interval
                gap_count = int((diffs > median_diff * 2.5).sum())
                if gap_count > 2:
                    notes.append(f"Gappy bars: {gap_count} gaps in last {len(recent)} bars")

    # Unusual volume
    vol_ratio = raw_indicators.get("vol_ratio_5d")
    if vol_ratio is not None and vol_ratio > 3.0:
        notes.append(f"Unusual volume: {vol_ratio:.1f}x 5-day average")

    # MA cross info
    ma_cross = raw_indicators.get("ma_cross_state", "none")
    if ma_cross == "golden":
        notes.append("Golden cross (MA50 > MA200)")
    elif ma_cross == "death":
        notes.append("Death cross (MA50 < MA200)")

    # RSI extremes
    rsi = raw_indicators.get("rsi14")
    if rsi is not None:
        if rsi < 25:
            notes.append(f"RSI deeply oversold ({rsi:.1f})")
        elif rsi > 75:
            notes.append(f"RSI deeply overbought ({rsi:.1f})")

    # Divergence flags from pipeline
    rsi_div = result.signals.get("rsi_divergence", 0.0)
    macd_div = result.signals.get("macd_divergence", 0.0)
    if abs(rsi_div) > 0.3:
        direction = "bullish" if rsi_div > 0 else "bearish"
        notes.append(f"RSI {direction} divergence detected")
    if abs(macd_div) > 0.3:
        direction = "bullish" if macd_div > 0 else "bearish"
        notes.append(f"MACD {direction} divergence detected")

    # Volume contradiction
    if result.volume_contradiction:
        notes.append("Volume contradicts price direction")

    # Dedup proximity
    if dedup.notes_for_claude:
        notes.append(dedup.notes_for_claude)

    return notes


# ---------------------------------------------------------------------------
# Build scored ticker from analysis result
# ---------------------------------------------------------------------------


def build_scored_ticker(
    result: AnalysisResult,
    df: pd.DataFrame,
    dedup: DedupStatus,
) -> ScoredTicker:
    """Transform an AnalysisResult into a ScoredTicker for the pre-scorer response."""
    raw = extract_raw_indicators(df)

    # Remap category scores to 0-10
    trend_score = remap_score(result.category_scores.get("trend", 0.0))
    momentum_score = remap_score(result.category_scores.get("momentum", 0.0))
    volatility_score = remap_score(result.category_scores.get("volatility", 0.0))
    volume_score = remap_score(result.category_scores.get("volume", 0.0))

    ta_composite = compute_ta_composite(result.category_scores)

    # Finalize dedup with actual composite
    final_dedup = finalize_dedup(dedup, ta_composite)

    pattern = classify_pattern(result.signals, result.category_scores, ta_composite)
    levels = compute_candidate_levels(result.meta, ta_composite)
    notes = generate_notes(df, raw, result, final_dedup)

    return ScoredTicker(
        ticker=result.symbol,
        indicators=IndicatorBreakdown(
            trend=TrendIndicators(
                ma50=raw.get("ma50"),
                ma200=raw.get("ma200"),
                ma_cross_state=raw.get("ma_cross_state", "none"),
                raw_score=trend_score,
            ),
            momentum=MomentumIndicators(
                rsi14=raw.get("rsi14"),
                macd_hist=raw.get("macd_hist"),
                raw_score=momentum_score,
            ),
            volatility=VolatilityIndicators(
                atr14_pct=raw.get("atr14_pct"),
                bb_width_pct=raw.get("bb_width_pct"),
                raw_score=volatility_score,
            ),
            volume=VolumeIndicators(
                vol_ratio_5d=raw.get("vol_ratio_5d"),
                raw_score=volume_score,
            ),
        ),
        composite_score=ta_composite,
        pattern_signature=pattern,
        candidate_levels=levels,
        dedup_status=final_dedup,
        notes_for_claude=notes,
    )
