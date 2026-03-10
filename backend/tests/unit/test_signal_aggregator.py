"""Unit tests for signal aggregator.

Tests cover:
- Aggregation handles missing YOLOv8 results (empty chart_patterns)
- Aggregation handles missing Chronos forecast (None forecast fields)
- Aggregation returns None when no P0 scanner results exist
- Aggregation returns None for unknown symbol
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.analysis.signal_aggregator import AggregatedSignals, aggregate_signals


# ── Helpers ──────────────────────────────────────────────────────────────────


def _mock_cache_value(
    composite: float = 0.5,
    signals: dict[str, float] | None = None,
    category_scores: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Build a mock indicator_cache JSONB value."""
    return {
        "symbol": "TEST",
        "composite_score": composite,
        "category_scores": category_scores or {
            "trend": 0.6, "momentum": 0.4, "volume": 0.2,
            "volatility": 0.1, "support_resistance": 0.3,
            "divergence": 0.0, "pattern": 0.1,
        },
        "profile_matches": ["TrendFollowing"],
        "signals": signals or {
            "rsi": 0.3, "macd": 0.4, "ema_stack": 0.6,
            "adx_dmi": 0.5, "supertrend": 0.7, "stochastic": 0.2,
            "ttm_squeeze": 0.3, "fibonacci": 0.2, "pivot_points": 0.1,
        },
        "meta": {
            "last_price": 150.0,
            "atr": 3.5,
            "atr_pct": 2.3,
        },
        "harmonics": None,
        "is_actionable": True,
        "volume_contradiction": False,
    }


class _FakeRow:
    """Simulates a SQLAlchemy result row for indicator_cache."""
    def __init__(self, value: dict[str, Any], time: datetime):
        self._data = (value, time)

    def __getitem__(self, idx: int) -> Any:
        return self._data[idx]


class _FakeScalarResult:
    """Simulates scalar_one_or_none() result."""
    def __init__(self, value: Any = None):
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeFirstResult:
    """Simulates .first() result."""
    def __init__(self, row: Any = None):
        self._row = row

    def first(self) -> Any:
        return self._row


class _FakeScalarsResult:
    """Simulates .scalars().all() result."""
    def __init__(self, items: list[Any] | None = None):
        self._items = items or []

    def scalars(self) -> "_FakeScalarsResult":
        return self

    def all(self) -> list[Any]:
        return self._items


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.unit
class TestAggregateSignals:
    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_symbol(self) -> None:
        """aggregate_signals returns None when symbol doesn't exist."""
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_FakeScalarResult(None))
        result = await aggregate_signals("UNKNOWN", db)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_cache(self) -> None:
        """aggregate_signals returns None when no indicator_cache entry exists."""
        db = AsyncMock()
        # First call: symbol lookup returns id=1
        # Second call: indicator_cache lookup returns None
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(1),
                _FakeFirstResult(None),
            ]
        )
        result = await aggregate_signals("AAPL", db)
        assert result is None

    @pytest.mark.asyncio
    async def test_handles_missing_yolo_patterns(self) -> None:
        """When no YOLO patterns exist, chart_patterns should be empty list."""
        now = datetime.now(UTC)
        cache_value = _mock_cache_value()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(1),           # symbol lookup
                _FakeFirstResult(               # indicator_cache
                    _FakeRow(cache_value, now),
                ),
                _FakeScalarsResult([]),          # pattern_detections (empty)
                _FakeScalarResult(None),         # forecast_cache (None)
            ]
        )

        result = await aggregate_signals("AAPL", db)
        assert result is not None
        assert result.chart_patterns == []
        assert result.composite_score == pytest.approx(0.5)
        assert result.last_close == pytest.approx(150.0)

    @pytest.mark.asyncio
    async def test_handles_missing_forecast(self) -> None:
        """When no Chronos forecast exists, forecast fields should be None."""
        now = datetime.now(UTC)
        cache_value = _mock_cache_value()

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(1),           # symbol lookup
                _FakeFirstResult(               # indicator_cache
                    _FakeRow(cache_value, now),
                ),
                _FakeScalarsResult([]),          # pattern_detections
                _FakeScalarResult(None),         # forecast_cache (None)
            ]
        )

        result = await aggregate_signals("AAPL", db)
        assert result is not None
        assert result.forecast_direction is None
        assert result.forecast_expected_move_pct is None
        assert result.forecast_confidence is None

    @pytest.mark.asyncio
    async def test_populates_core_fields(self) -> None:
        """Verify core fields are populated from indicator_cache."""
        now = datetime.now(UTC)
        cache_value = _mock_cache_value(composite=0.72)

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(1),
                _FakeFirstResult(_FakeRow(cache_value, now)),
                _FakeScalarsResult([]),
                _FakeScalarResult(None),
            ]
        )

        result = await aggregate_signals("AAPL", db)
        assert result is not None
        assert result.symbol == "AAPL"
        assert result.timeframe == "D1"
        assert result.composite_score == pytest.approx(0.72)
        assert result.category_scores["trend"] == pytest.approx(0.6)
        assert result.active_profile_matches == ["TrendFollowing"]
        assert result.atr_pct == pytest.approx(2.3)

    @pytest.mark.asyncio
    async def test_ew_summary_from_signals(self) -> None:
        """Elliott Wave summary populated when ew signals are present."""
        now = datetime.now(UTC)
        cache_value = _mock_cache_value(
            signals={
                "rsi": 0.3, "macd": 0.4, "ema_stack": 0.6,
                "ew_ratio_quality": 0.8, "ew_wave3_active": 0.9,
            }
        )

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                _FakeScalarResult(1),
                _FakeFirstResult(_FakeRow(cache_value, now)),
                _FakeScalarsResult([]),
                _FakeScalarResult(None),
            ]
        )

        result = await aggregate_signals("AAPL", db)
        assert result is not None
        assert result.ew_summary is not None
        assert "Wave 3" in result.ew_summary
