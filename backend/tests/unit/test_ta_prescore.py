"""
Unit tests for the TA Pre-Scorer service — pure logic, no I/O.

Covers:
- Score remapping (pipeline [-1,+1] → TA [0,10])
- TA composite computation (4-category weighted average)
- Pattern signature classifier (deterministic, mutually exclusive)
- Candidate technical levels (ATR-based, neutral band)
- Dedup finalization (score-delta rules)
- Notes generation
- Full build_scored_ticker integration

Reference: TC-SWE-95 Phase 1 AC.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.analysis.pipeline import AnalysisResult, run_analysis
from app.api.ta_service import (
    build_scored_ticker,
    classify_pattern,
    compute_candidate_levels,
    compute_ta_composite,
    finalize_dedup,
    generate_notes,
    remap_score,
)
from app.schemas.ta import DedupStatus
from tests.generators import gen_consolidation, gen_downtrend, gen_uptrend

# ---------------------------------------------------------------------------
# Score remapping
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRemapScore:
    def test_min_maps_to_zero(self) -> None:
        assert remap_score(-1.0) == 0.0

    def test_max_maps_to_ten(self) -> None:
        assert remap_score(1.0) == 10.0

    def test_neutral_maps_to_five(self) -> None:
        assert remap_score(0.0) == 5.0

    def test_range_preservation(self) -> None:
        for val in [-1.0, -0.5, 0.0, 0.25, 0.5, 0.75, 1.0]:
            result = remap_score(val)
            assert 0.0 <= result <= 10.0, f"remap_score({val}) = {result} out of [0, 10]"


# ---------------------------------------------------------------------------
# TA composite computation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTAComposite:
    def test_all_max_gives_ten(self) -> None:
        scores = {"trend": 1.0, "momentum": 1.0, "volatility": 1.0, "volume": 1.0}
        assert compute_ta_composite(scores) == 10.0

    def test_all_min_gives_zero(self) -> None:
        scores = {"trend": -1.0, "momentum": -1.0, "volatility": -1.0, "volume": -1.0}
        assert compute_ta_composite(scores) == 0.0

    def test_all_neutral_gives_five(self) -> None:
        scores = {"trend": 0.0, "momentum": 0.0, "volatility": 0.0, "volume": 0.0}
        assert compute_ta_composite(scores) == 5.0

    def test_weights_correct(self) -> None:
        # Only trend is max, rest neutral → 0.4*10 + 0.3*5 + 0.2*5 + 0.1*5 = 7.0
        scores = {"trend": 1.0, "momentum": 0.0, "volatility": 0.0, "volume": 0.0}
        assert compute_ta_composite(scores) == 7.0

    def test_missing_categories_default_zero(self) -> None:
        scores: dict[str, float] = {}
        assert compute_ta_composite(scores) == 5.0  # all default to 0.0 → remap to 5.0

    def test_result_in_range(self) -> None:
        import random

        random.seed(42)
        for _ in range(100):
            scores = {
                cat: random.uniform(-1.0, 1.0)
                for cat in ["trend", "momentum", "volatility", "volume"]
            }
            result = compute_ta_composite(scores)
            assert 0.0 <= result <= 10.0


# ---------------------------------------------------------------------------
# Pattern signature classifier
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestPatternClassifier:
    def test_breakout(self) -> None:
        signals = {
            "ema_stack": 0.33,
            "adx_dmi": 0.5,
            "supertrend": 1.0,
            "rsi": -0.1,
            "bb_pct_b": 0.0,
        }
        cats = {"trend": 0.5, "momentum": 0.3, "volume": 0.2, "volatility": 0.0}
        assert classify_pattern(signals, cats, 7.0) == "breakout"

    def test_mean_reversion(self) -> None:
        signals = {
            "ema_stack": -0.33,
            "adx_dmi": 0.1,
            "supertrend": -1.0,
            "rsi": 0.5,
            "bb_pct_b": 0.5,
        }
        cats = {"trend": -0.3, "momentum": 0.2, "volume": 0.0, "volatility": 0.1}
        assert classify_pattern(signals, cats, 5.0) == "mean_reversion"

    def test_uptrend_continuation(self) -> None:
        signals = {
            "ema_stack": 0.8,
            "adx_dmi": 0.15,
            "supertrend": 1.0,
            "rsi": -0.1,
            "bb_pct_b": -0.2,
        }
        cats = {"trend": 0.5, "momentum": 0.2, "volume": 0.05, "volatility": 0.0}
        assert classify_pattern(signals, cats, 6.5) == "uptrend_continuation"

    def test_consolidation(self) -> None:
        signals = {
            "ema_stack": 0.0,
            "adx_dmi": 0.05,
            "supertrend": 0.0,
            "rsi": 0.0,
            "bb_pct_b": 0.0,
        }
        cats = {"trend": 0.0, "momentum": 0.0, "volume": 0.0, "volatility": 0.0}
        assert classify_pattern(signals, cats, 5.0) == "consolidation"

    def test_chop_fallback(self) -> None:
        # High ADX but low volume and low composite — none of the rules match
        signals = {
            "ema_stack": -1.0,
            "adx_dmi": 0.5,
            "supertrend": -1.0,
            "rsi": -0.5,
            "bb_pct_b": -0.5,
        }
        cats = {"trend": -0.5, "momentum": -0.5, "volume": -0.3, "volatility": -0.2}
        assert classify_pattern(signals, cats, 2.0) == "chop"

    def test_precedence_breakout_over_uptrend(self) -> None:
        """Breakout has higher priority than uptrend_continuation."""
        signals = {
            "ema_stack": 0.8,
            "adx_dmi": 0.5,
            "supertrend": 1.0,
            "rsi": -0.1,
            "bb_pct_b": -0.2,
        }
        cats = {"trend": 0.5, "momentum": 0.3, "volume": 0.2, "volatility": 0.0}
        assert classify_pattern(signals, cats, 7.0) == "breakout"

    def test_all_signatures_reachable(self) -> None:
        """Each pattern signature can be produced."""
        seen = set()
        test_cases = [
            (
                {"adx_dmi": 0.5, "ema_stack": 0.3, "supertrend": 1.0, "rsi": -0.1, "bb_pct_b": 0.0},
                {"volume": 0.2, "trend": 0.5, "momentum": 0.3, "volatility": 0.0},
                7.0,
            ),
            (
                {
                    "adx_dmi": 0.1,
                    "ema_stack": -0.3,
                    "supertrend": -1.0,
                    "rsi": 0.5,
                    "bb_pct_b": 0.5,
                },
                {"volume": 0.0, "trend": -0.3, "momentum": 0.2, "volatility": 0.1},
                5.0,
            ),
            (
                {
                    "adx_dmi": 0.15,
                    "ema_stack": 0.8,
                    "supertrend": 1.0,
                    "rsi": -0.1,
                    "bb_pct_b": -0.2,
                },
                {"volume": 0.05, "trend": 0.5, "momentum": 0.2, "volatility": 0.0},
                6.5,
            ),
            (
                {"adx_dmi": 0.05, "ema_stack": 0.0, "supertrend": 0.0, "rsi": 0.0, "bb_pct_b": 0.0},
                {"volume": 0.0, "trend": 0.0, "momentum": 0.0, "volatility": 0.0},
                5.0,
            ),
            (
                {
                    "adx_dmi": 0.5,
                    "ema_stack": -1.0,
                    "supertrend": -1.0,
                    "rsi": -0.5,
                    "bb_pct_b": -0.5,
                },
                {"volume": -0.3, "trend": -0.5, "momentum": -0.5, "volatility": -0.2},
                2.0,
            ),
        ]
        for sigs, cats, comp in test_cases:
            seen.add(classify_pattern(sigs, cats, comp))
        assert seen == {
            "breakout",
            "mean_reversion",
            "uptrend_continuation",
            "consolidation",
            "chop",
        }


# ---------------------------------------------------------------------------
# Candidate levels
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCandidateLevels:
    def test_long_direction(self) -> None:
        meta = {"last_price": 100.0, "atr": 5.0}
        levels = compute_candidate_levels(meta, 7.0)
        assert levels is not None
        assert levels.entry == 100.0
        assert levels.stop == 90.0  # 100 - 2*5
        assert levels.target == 115.0  # 100 + 1.5*10
        assert levels.r_multiple == 1.5
        assert "below" in levels.stop_basis
        assert "above" in levels.target_basis

    def test_short_direction(self) -> None:
        meta = {"last_price": 100.0, "atr": 5.0}
        levels = compute_candidate_levels(meta, 3.0)
        assert levels is not None
        assert levels.entry == 100.0
        assert levels.stop == 110.0  # 100 + 2*5
        assert levels.target == 85.0  # 100 - 1.5*10
        assert "above" in levels.stop_basis
        assert "below" in levels.target_basis

    def test_neutral_band_returns_none(self) -> None:
        meta = {"last_price": 100.0, "atr": 5.0}
        assert compute_candidate_levels(meta, 5.0) is None
        assert compute_candidate_levels(meta, 4.5) is None
        assert compute_candidate_levels(meta, 5.5) is None

    def test_zero_price_returns_none(self) -> None:
        meta = {"last_price": 0.0, "atr": 5.0}
        assert compute_candidate_levels(meta, 8.0) is None

    def test_zero_atr_returns_none(self) -> None:
        meta = {"last_price": 100.0, "atr": 0.0}
        assert compute_candidate_levels(meta, 8.0) is None


# ---------------------------------------------------------------------------
# Dedup finalization
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDedupFinalization:
    def test_no_existing_signal(self) -> None:
        dedup = DedupStatus(filing_recommended=True)
        result = finalize_dedup(dedup, 7.5)
        assert result.filing_recommended is True
        assert result.skip_reason is None

    def test_small_delta_skips(self) -> None:
        dedup = DedupStatus(
            registry_match_url="https://notion.so/abc123",
            registry_match_score=7.0,
        )
        result = finalize_dedup(dedup, 7.5)  # delta = 0.5
        assert result.filing_recommended is False
        assert "dedup" in (result.skip_reason or "")
        assert "delta 0.5" in (result.skip_reason or "")

    def test_large_delta_files_with_note(self) -> None:
        dedup = DedupStatus(
            registry_match_url="https://notion.so/abc123",
            registry_match_score=5.0,
        )
        result = finalize_dedup(dedup, 7.5)  # delta = 2.5
        assert result.filing_recommended is True
        assert result.notes_for_claude is not None
        assert "mark-superseded" in result.notes_for_claude

    def test_exact_threshold_boundary(self) -> None:
        dedup = DedupStatus(
            registry_match_url="https://notion.so/abc123",
            registry_match_score=6.0,
        )
        # delta = exactly 1.0 → should skip (≤ 1.0)
        result = finalize_dedup(dedup, 7.0)
        assert result.filing_recommended is False

        # delta = 1.01 → should file
        result2 = finalize_dedup(dedup, 7.01)
        assert result2.filing_recommended is True


# ---------------------------------------------------------------------------
# Notes generation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNotesGeneration:
    def _make_result(self, **overrides: dict) -> AnalysisResult:
        defaults = {
            "symbol": "TEST",
            "composite_score": 0.5,
            "category_scores": {
                "trend": 0.3,
                "momentum": 0.2,
                "volatility": 0.1,
                "volume": 0.1,
                "support_resistance": 0.0,
                "divergence": 0.0,
                "pattern": 0.0,
            },
            "profile_matches": [],
            "signals": {},
            "meta": {"atr": 5.0, "last_price": 100.0, "volume_ratio": 1.0},
        }
        defaults.update(overrides)
        return AnalysisResult(**defaults)

    def test_unusual_volume_flagged(self) -> None:
        df = gen_uptrend(bars=250)
        result = self._make_result()
        dedup = DedupStatus()
        notes = generate_notes(df, {"vol_ratio_5d": 4.2}, result, dedup)
        assert any("Unusual volume" in n for n in notes)

    def test_golden_cross_flagged(self) -> None:
        df = gen_uptrend(bars=250)
        result = self._make_result()
        dedup = DedupStatus()
        notes = generate_notes(df, {"ma_cross_state": "golden"}, result, dedup)
        assert any("Golden cross" in n for n in notes)

    def test_rsi_oversold_flagged(self) -> None:
        df = gen_uptrend(bars=250)
        result = self._make_result()
        dedup = DedupStatus()
        notes = generate_notes(df, {"rsi14": 22.0}, result, dedup)
        assert any("oversold" in n for n in notes)

    def test_divergence_flagged(self) -> None:
        df = gen_uptrend(bars=250)
        result = self._make_result(signals={"rsi_divergence": 0.5})
        dedup = DedupStatus()
        notes = generate_notes(df, {}, result, dedup)
        assert any("RSI bullish divergence" in n for n in notes)

    def test_volume_contradiction_flagged(self) -> None:
        df = gen_uptrend(bars=250)
        result = self._make_result(volume_contradiction=True)
        dedup = DedupStatus()
        notes = generate_notes(df, {}, result, dedup)
        assert any("contradicts" in n for n in notes)

    def test_dedup_note_included(self) -> None:
        df = gen_uptrend(bars=250)
        result = self._make_result()
        dedup = DedupStatus(notes_for_claude="previous signal X; consider mark-superseded")
        notes = generate_notes(df, {}, result, dedup)
        assert any("mark-superseded" in n for n in notes)


# ---------------------------------------------------------------------------
# build_scored_ticker integration (with real pipeline)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildScoredTicker:
    def test_uptrend_produces_valid_ticker(self) -> None:
        df = gen_uptrend(bars=250)
        result = run_analysis(df, "NVDA")
        dedup = DedupStatus()
        scored = build_scored_ticker(result, df, dedup)

        assert scored.ticker == "NVDA"
        assert 0.0 <= scored.composite_score <= 10.0
        assert scored.pattern_signature in {
            "uptrend_continuation",
            "breakout",
            "mean_reversion",
            "consolidation",
            "chop",
        }
        assert scored.indicators.trend.raw_score >= 0.0
        assert scored.indicators.momentum.raw_score >= 0.0
        assert scored.dedup_status.filing_recommended is True

    def test_downtrend_produces_valid_ticker(self) -> None:
        df = gen_downtrend(bars=250)
        result = run_analysis(df, "META")
        dedup = DedupStatus()
        scored = build_scored_ticker(result, df, dedup)

        assert scored.ticker == "META"
        assert 0.0 <= scored.composite_score <= 10.0

    def test_consolidation_produces_valid_ticker(self) -> None:
        df = gen_consolidation(bars=250)
        result = run_analysis(df, "AAPL")
        dedup = DedupStatus()
        scored = build_scored_ticker(result, df, dedup)

        assert scored.ticker == "AAPL"
        assert 0.0 <= scored.composite_score <= 10.0

    def test_raw_indicators_populated(self) -> None:
        df = gen_uptrend(bars=250)
        result = run_analysis(df, "AMD")
        dedup = DedupStatus()
        scored = build_scored_ticker(result, df, dedup)

        # Raw indicators should be populated (not None) for sufficient data
        assert scored.indicators.trend.ma50 is not None
        assert scored.indicators.trend.ma200 is not None
        assert scored.indicators.momentum.rsi14 is not None
        assert scored.indicators.trend.ma_cross_state in {"golden", "death", "none"}

    def test_single_bar_edge_case(self) -> None:
        """Single-bar DataFrame should not crash."""
        import pandas as pd

        df = pd.DataFrame(
            {
                "time": pd.bdate_range("2024-01-02", periods=1),
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [1000000],
            }
        )
        result = run_analysis(df, "EDGE")
        dedup = DedupStatus()
        scored = build_scored_ticker(result, df, dedup)
        assert scored.ticker == "EDGE"
        assert 0.0 <= scored.composite_score <= 10.0

    def test_zero_volume_edge_case(self) -> None:
        """Zero-volume bars should not crash."""
        import numpy as np
        import pandas as pd

        dates = pd.bdate_range("2024-01-02", periods=250)
        rng = np.random.default_rng(42)
        closes = 100.0 + np.cumsum(rng.normal(0, 1, 250))
        df = pd.DataFrame(
            {
                "time": dates,
                "open": closes + rng.normal(0, 0.5, 250),
                "high": closes + np.abs(rng.normal(0, 1, 250)),
                "low": closes - np.abs(rng.normal(0, 1, 250)),
                "close": closes,
                "volume": np.zeros(250, dtype=int),
            }
        )
        result = run_analysis(df, "ZERO_VOL")
        dedup = DedupStatus()
        scored = build_scored_ticker(result, df, dedup)
        assert scored.ticker == "ZERO_VOL"
        assert 0.0 <= scored.composite_score <= 10.0


# ---------------------------------------------------------------------------
# Batch dedup check (mocked Notion)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBatchDedupCheck:
    @pytest.mark.asyncio
    async def test_no_existing_signals(self) -> None:
        from app.api.ta_service import batch_dedup_check

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value={"results": []})

        with patch("app.agents_common.notion_client._get_client", return_value=mock_client):
            result = await batch_dedup_check(["NVDA", "AMD"], 24)

        assert result["NVDA"].filing_recommended is True
        assert result["NVDA"].registry_match_url is None
        assert result["AMD"].filing_recommended is True

    @pytest.mark.asyncio
    async def test_existing_signal_found(self) -> None:
        from app.api.ta_service import batch_dedup_check

        mock_page = {
            "id": "abc-123",
            "properties": {
                "Ticker": {"title": [{"plain_text": "NVDA"}]},
                "Score": {"number": 7.5},
                "Agent": {"rich_text": [{"plain_text": "technical-analyst"}]},
                "Date": {"date": {"start": "2026-04-20T14:00:00Z"}},
            },
        }

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(return_value={"results": [mock_page]})

        with patch("app.agents_common.notion_client._get_client", return_value=mock_client):
            result = await batch_dedup_check(["NVDA", "AMD"], 24)

        assert result["NVDA"].registry_match_url is not None
        assert result["NVDA"].registry_match_score == 7.5
        assert result["AMD"].filing_recommended is True
        assert result["AMD"].registry_match_url is None

    @pytest.mark.asyncio
    async def test_notion_failure_defaults_to_filing(self) -> None:
        from app.api.ta_service import batch_dedup_check

        mock_client = AsyncMock()
        mock_client.request = AsyncMock(side_effect=Exception("Notion down"))

        with patch("app.agents_common.notion_client._get_client", return_value=mock_client):
            result = await batch_dedup_check(["NVDA"], 24)

        assert result["NVDA"].filing_recommended is True


# ---------------------------------------------------------------------------
# Filter reason classification (TC-SWE-102)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestClassifyFilterReason:
    def test_not_in_db(self) -> None:
        from app.api.ta import _classify_filter_reason

        assert _classify_filter_reason("ticker not in Stonky DB") == "not_in_db"

    def test_insufficient_ohlcv(self) -> None:
        from app.api.ta import _classify_filter_reason

        assert _classify_filter_reason("insufficient OHLCV data") == "insufficient_ohlcv"

    def test_ohlcv_fetch_failed(self) -> None:
        from app.api.ta import _classify_filter_reason

        assert _classify_filter_reason("OHLCV fetch failed") == "ohlcv_fetch_failed"

    def test_below_threshold(self) -> None:
        from app.api.ta import _classify_filter_reason

        assert (
            _classify_filter_reason("composite_score 3.2 below threshold 4.5") == "below_threshold"
        )

    def test_dedup(self) -> None:
        from app.api.ta import _classify_filter_reason

        assert _classify_filter_reason("dedup filtered") == "dedup"
        assert _classify_filter_reason("dedup: delta 0.5 below 1.0") == "dedup"

    def test_unknown_passes_through(self) -> None:
        from app.api.ta import _classify_filter_reason

        assert _classify_filter_reason("some other reason") == "some other reason"


@pytest.mark.unit
class TestPrescoreMetadataDiagnostics:
    """Verify PrescoreMetadata includes TC-SWE-102 diagnostic fields."""

    def test_filter_reasons_schema(self) -> None:
        from app.schemas.ta import PrescoreMetadata

        meta = PrescoreMetadata(
            tickers_input=10,
            tickers_scored=8,
            tickers_above_threshold=3,
            tickers_filtered_dedup=2,
            stonky_pipeline_latency_ms=500,
            symbols_resolved=10,
            filter_reasons={"not_in_db": 0, "insufficient_ohlcv": 2, "below_threshold": 3},
            backfill_stats={"hydrated": 5, "failed": 1, "skipped": 4},
        )
        assert meta.symbols_resolved == 10
        assert meta.filter_reasons["insufficient_ohlcv"] == 2
        assert meta.backfill_stats["hydrated"] == 5

    def test_defaults_when_omitted(self) -> None:
        from app.schemas.ta import PrescoreMetadata

        meta = PrescoreMetadata(
            tickers_input=5,
            tickers_scored=5,
            tickers_above_threshold=2,
            tickers_filtered_dedup=0,
            stonky_pipeline_latency_ms=100,
        )
        assert meta.symbols_resolved == 0
        assert meta.filter_reasons == {}
        assert meta.backfill_stats == {}


@pytest.mark.unit
class TestHydrateSchemas:
    """Verify hydrate request/response schemas."""

    def test_hydrate_request_valid(self) -> None:
        from app.schemas.ta import HydrateRequest

        req = HydrateRequest(tickers=["AAPL", "NVDA"])
        assert len(req.tickers) == 2

    def test_hydrate_request_rejects_empty(self) -> None:
        from pydantic import ValidationError

        from app.schemas.ta import HydrateRequest

        with pytest.raises(ValidationError):
            HydrateRequest(tickers=[])

    def test_hydrate_response(self) -> None:
        from app.schemas.ta import HydrateResponse

        resp = HydrateResponse(tickers_submitted=10)
        assert resp.status == "queued"
        assert resp.tickers_submitted == 10
