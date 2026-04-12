"""
Unit tests for all backtest strategy classes.

Tests cover:
- Signal array shape and dtype contracts for all strategies
- Directional correctness (entries in uptrend for trend-following strategies)
- No-lookahead guarantee for EMACrossoverStrategy
- Stop/target price population for profile strategies
- YOLO pattern strategy: no detections → no entries; detections → entry on next bar
- CustomStrategy: AND/OR logic and crosses_above operator
- Strategy metadata: describe() and param_space defined

All tests use synthetic OHLCV data only — no DB, no I/O, no network.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.generators import gen_breakout, gen_consolidation, gen_uptrend, gen_v_recovery

# ---------------------------------------------------------------------------
# Shared enrichment helper — adds all indicator columns expected by strategies
# ---------------------------------------------------------------------------


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Set time as DatetimeIndex, apply all indicator compute functions, and return an
    enriched copy with all indicator columns present.

    Each compute_*() function returns a new DataFrame (it does df.copy() internally),
    so this helper chains those return values. The 'time' column from generators is a
    plain column with a RangeIndex; it must be promoted to the DatetimeIndex first to
    satisfy compute_vwap() and match what app/analysis/pipeline.py does at line 85.
    """
    from app.analysis.indicators.momentum import compute_macd, compute_rsi, compute_stoch
    from app.analysis.indicators.trend import compute_adx, compute_ema, compute_supertrend
    from app.analysis.indicators.volatility import compute_atr, compute_bbands, compute_ttm_squeeze
    from app.analysis.indicators.volume import compute_cmf, compute_obv, compute_vwap

    if "time" in df.columns:
        df = df.set_index("time")

    df = compute_ema(df)
    df = compute_adx(df)
    df = compute_supertrend(df)
    df = compute_rsi(df)
    df = compute_macd(df)
    df = compute_stoch(df)
    df = compute_bbands(df)
    df = compute_atr(df)
    df = compute_ttm_squeeze(df)
    df = compute_obv(df)
    df = compute_vwap(df)
    df = compute_cmf(df)
    return df


# ---------------------------------------------------------------------------
# Parametrized fixtures for all strategy classes
# ---------------------------------------------------------------------------

# Indicator strategies instantiated with defaults
_INDICATOR_STRATEGY_FACTORIES = [
    pytest.param(
        lambda: __import__(
            "app.backtesting.strategies.indicator_strategies",
            fromlist=["EMACrossoverStrategy"],
        ).EMACrossoverStrategy(),
        id="EMACrossoverStrategy",
    ),
    pytest.param(
        lambda: __import__(
            "app.backtesting.strategies.indicator_strategies",
            fromlist=["RSIThresholdStrategy"],
        ).RSIThresholdStrategy(),
        id="RSIThresholdStrategy",
    ),
    pytest.param(
        lambda: __import__(
            "app.backtesting.strategies.indicator_strategies",
            fromlist=["MACDCrossStrategy"],
        ).MACDCrossStrategy(),
        id="MACDCrossStrategy",
    ),
    pytest.param(
        lambda: __import__(
            "app.backtesting.strategies.indicator_strategies",
            fromlist=["SupertrendStrategy"],
        ).SupertrendStrategy(),
        id="SupertrendStrategy",
    ),
]

# Profile strategies instantiated with defaults
_PROFILE_STRATEGY_FACTORIES = [
    pytest.param(
        lambda: __import__(
            "app.backtesting.strategies.profile_strategies",
            fromlist=["MomentumBreakoutStrategy"],
        ).MomentumBreakoutStrategy(),
        id="MomentumBreakoutStrategy",
    ),
    pytest.param(
        lambda: __import__(
            "app.backtesting.strategies.profile_strategies",
            fromlist=["TrendFollowingStrategy"],
        ).TrendFollowingStrategy(),
        id="TrendFollowingStrategy",
    ),
    pytest.param(
        lambda: __import__(
            "app.backtesting.strategies.profile_strategies",
            fromlist=["MeanReversionStrategy"],
        ).MeanReversionStrategy(),
        id="MeanReversionStrategy",
    ),
    pytest.param(
        lambda: __import__(
            "app.backtesting.strategies.profile_strategies",
            fromlist=["HarmonicSetupStrategy"],
        ).HarmonicSetupStrategy(),
        id="HarmonicSetupStrategy",
    ),
]

_ALL_STRATEGY_FACTORIES = _INDICATOR_STRATEGY_FACTORIES + _PROFILE_STRATEGY_FACTORIES


# ===========================================================================
# Test class: signal shape and dtype contracts (all strategies)
# ===========================================================================


@pytest.mark.unit
class TestSignalShapeContracts:
    """All strategies must return entries/exits arrays of the exact same length as df."""

    @pytest.mark.parametrize("factory", _ALL_STRATEGY_FACTORIES)
    def test_signal_length_matches_dataframe(self, factory) -> None:
        """Signal arrays must be the same length as the input DataFrame."""
        from app.backtesting.strategies.base import SignalResult

        df = _enrich(gen_uptrend(bars=200, seed=42))
        strategy = factory()
        result = strategy.generate_signals(df)

        assert isinstance(result, SignalResult)
        assert len(result.entries) == len(df), (
            f"{strategy.name}: entries length {len(result.entries)} != df length {len(df)}"
        )
        assert len(result.exits) == len(df), (
            f"{strategy.name}: exits length {len(result.exits)} != df length {len(df)}"
        )

    @pytest.mark.parametrize("factory", _ALL_STRATEGY_FACTORIES)
    def test_entries_exits_are_bool_dtype(self, factory) -> None:
        """entries and exits arrays must have boolean dtype."""
        df = _enrich(gen_uptrend(bars=200, seed=42))
        strategy = factory()
        result = strategy.generate_signals(df)

        assert result.entries.dtype == bool, (
            f"{strategy.name}: entries.dtype={result.entries.dtype}, expected bool"
        )
        assert result.exits.dtype == bool, (
            f"{strategy.name}: exits.dtype={result.exits.dtype}, expected bool"
        )

    @pytest.mark.parametrize("factory", _PROFILE_STRATEGY_FACTORIES)
    def test_profile_strategy_signals_on_all_generators(self, factory) -> None:
        """Profile strategies must return correct shape/dtype across all synthetic regimes."""
        generators = [gen_uptrend, gen_consolidation, gen_v_recovery, gen_breakout]
        for gen_fn in generators:
            df = _enrich(gen_fn(bars=200, seed=42))
            strategy = factory()
            result = strategy.generate_signals(df)

            assert len(result.entries) == len(df), (
                f"{strategy.name} on {gen_fn.__name__}: entries length mismatch"
            )
            assert result.entries.dtype == bool, (
                f"{strategy.name} on {gen_fn.__name__}: entries not bool dtype"
            )


# ===========================================================================
# Test class: EMACrossoverStrategy specific behaviour
# ===========================================================================


@pytest.mark.unit
class TestEMACrossoverStrategy:
    """Focused tests on EMACrossoverStrategy correctness and metadata."""

    def test_produces_at_least_one_entry_in_uptrend(self) -> None:
        """Uptrend data must trigger at least one EMA bullish crossover."""
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        df = _enrich(gen_uptrend(bars=200, seed=42))
        result = EMACrossoverStrategy().generate_signals(df)
        assert result.entries.any(), (
            "EMACrossoverStrategy produced no entries on uptrend data; "
            "fast EMA should cross above slow EMA at least once in a sustained uptrend"
        )

    def test_no_simultaneous_entry_and_exit(self) -> None:
        """A bar cannot be both an entry and an exit signal."""
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        for gen_fn in [gen_uptrend, gen_consolidation, gen_v_recovery]:
            df = _enrich(gen_fn(bars=200, seed=42))
            result = EMACrossoverStrategy().generate_signals(df)
            simultaneous = result.entries & result.exits
            assert not simultaneous.any(), (
                f"EMACrossoverStrategy produced simultaneous entry+exit on {gen_fn.__name__} "
                f"at bars: {np.where(simultaneous)[0].tolist()}"
            )

    def test_describe_returns_nonempty_string(self) -> None:
        """describe() must return a non-empty human-readable string."""
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy(fast=9, slow=21)
        desc = strategy.describe()
        assert isinstance(desc, str) and len(desc) > 0
        # The description should mention the parameter values so callers can audit the config
        assert "9" in desc and "21" in desc, (
            f"describe() should include fast/slow params, got: {desc!r}"
        )

    def test_param_space_defined_and_non_empty(self) -> None:
        """param_space must exist and contain at least the fast and slow keys."""
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        assert isinstance(strategy.param_space, dict)
        assert "fast" in strategy.param_space
        assert "slow" in strategy.param_space
        # Each axis must have multiple candidate values so sweeps can run
        assert len(strategy.param_space["fast"]) > 1
        assert len(strategy.param_space["slow"]) > 1

    def test_no_lookahead_truncation_does_not_change_first_bars(self) -> None:
        """Signals for bars 0-179 must be identical whether or not bars 180-199 exist.

        This is the core no-lookahead guarantee: the strategy must be causal.
        EMACrossoverStrategy uses np.roll which is defined only on fixed-length arrays;
        the test verifies the signal for bar i is not influenced by bar i+k for any k > 0.
        """
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        df_full = _enrich(gen_uptrend(bars=200, seed=42))
        df_truncated = _enrich(gen_uptrend(bars=180, seed=42))

        strategy = EMACrossoverStrategy()
        result_full = strategy.generate_signals(df_full)
        result_trunc = strategy.generate_signals(df_truncated)

        # Compare first 180 bars — must be identical
        np.testing.assert_array_equal(
            result_full.entries[:180],
            result_trunc.entries[:180],
            err_msg=(
                "EMACrossoverStrategy entries differ for first 180 bars when trailing 20 bars "
                "are removed. Strategy is leaking future data (lookahead bias)."
            ),
        )
        np.testing.assert_array_equal(
            result_full.exits[:180],
            result_trunc.exits[:180],
            err_msg=(
                "EMACrossoverStrategy exits differ for first 180 bars when trailing 20 bars "
                "are removed. Strategy is leaking future data (lookahead bias)."
            ),
        )


# ===========================================================================
# Test class: MomentumBreakoutStrategy — stop prices populated on entries
# ===========================================================================


@pytest.mark.unit
class TestMomentumBreakoutStrategy:
    """MomentumBreakoutStrategy must populate stop_prices at every entry bar."""

    def test_stop_prices_present_when_entries_fire(self) -> None:
        """When entries occur, stop_prices must be non-None and finite at those bars."""
        from app.backtesting.strategies.profile_strategies import MomentumBreakoutStrategy

        # Use relaxed params so entries are more likely on synthetic data
        strategy = MomentumBreakoutStrategy(
            rsi_min=40,
            rsi_max=80,
            adx_min=10,
            volume_multiplier=1.1,
            squeeze_required=False,
        )
        df = _enrich(gen_uptrend(bars=200, seed=42))
        result = strategy.generate_signals(df)

        if not result.entries.any():
            pytest.skip(
                "MomentumBreakoutStrategy produced no entries on this synthetic data; "
                "relax parameters further if this becomes a persistent failure"
            )

        assert result.stop_prices is not None, "stop_prices must not be None when entries fired"
        entry_bars = np.where(result.entries)[0]
        for bar in entry_bars:
            assert np.isfinite(result.stop_prices[bar]), (
                f"stop_prices[{bar}] is NaN/Inf but entries[{bar}] is True"
            )

    def test_stop_prices_below_entry_close(self) -> None:
        """Stop prices must always be strictly below the closing price at entry bars."""
        from app.backtesting.strategies.profile_strategies import MomentumBreakoutStrategy

        strategy = MomentumBreakoutStrategy(
            rsi_min=40,
            rsi_max=80,
            adx_min=10,
            volume_multiplier=1.1,
            squeeze_required=False,
        )
        df = _enrich(gen_uptrend(bars=200, seed=42))
        result = strategy.generate_signals(df)

        if result.stop_prices is None or not result.entries.any():
            pytest.skip("No entries to validate stop prices against")

        close = df["close"].to_numpy()
        entry_bars = np.where(result.entries)[0]
        for bar in entry_bars:
            assert result.stop_prices[bar] < close[bar], (
                f"stop_prices[{bar}]={result.stop_prices[bar]:.4f} >= close[{bar}]={close[bar]:.4f}; "
                "long stop must be below entry price"
            )


# ===========================================================================
# Test class: YOLOPatternStrategy
# ===========================================================================


@pytest.mark.unit
class TestYOLOPatternStrategy:
    """YOLOPatternStrategy must be inert without pattern columns and reactive with them."""

    def test_no_detections_produces_no_entries(self) -> None:
        """DataFrame without yolo_pattern column must yield all-False entries."""
        from app.backtesting.strategies.pattern_strategies import YOLOPatternStrategy

        df = _enrich(gen_uptrend(bars=200, seed=42))
        # Confirm yolo_pattern is absent (no YOLO columns materialized)
        assert "yolo_pattern" not in df.columns

        result = YOLOPatternStrategy().generate_signals(df)
        assert not result.entries.any(), (
            "YOLOPatternStrategy produced entries even though yolo_pattern column is absent"
        )
        assert not result.exits.any(), (
            "YOLOPatternStrategy produced exits even though yolo_pattern column is absent"
        )

    def test_detection_at_bar_i_triggers_entry_at_bar_i_plus_one(self) -> None:
        """A YOLO detection at bar i must produce entry=True at bar i+1 (next-bar fill)."""
        from app.backtesting.strategies.pattern_strategies import YOLOPatternStrategy

        df = _enrich(gen_uptrend(bars=200, seed=42))

        # Manually inject a high-confidence bull_flag detection at bar 50
        detection_bar = 50
        df["yolo_pattern"] = None
        df["yolo_confidence"] = 0.0
        df.iloc[detection_bar, df.columns.get_loc("yolo_pattern")] = "bull_flag"
        df.iloc[detection_bar, df.columns.get_loc("yolo_confidence")] = 0.85

        strategy = YOLOPatternStrategy(pattern_names=["bull_flag"], min_confidence=0.7)
        result = strategy.generate_signals(df)

        assert result.entries[detection_bar + 1], (
            f"Expected entry at bar {detection_bar + 1} (bar after detection at {detection_bar}), "
            f"but entries[{detection_bar + 1}] is False"
        )
        # No other bars should be entries (only one detection injected)
        other_entry_bars = np.where(result.entries)[0]
        other_entry_bars = other_entry_bars[other_entry_bars != detection_bar + 1]
        assert len(other_entry_bars) == 0, (
            f"Unexpected entries at bars {other_entry_bars.tolist()} — only one detection injected"
        )

    def test_low_confidence_detection_skipped(self) -> None:
        """A detection below min_confidence must not produce an entry."""
        from app.backtesting.strategies.pattern_strategies import YOLOPatternStrategy

        df = _enrich(gen_uptrend(bars=200, seed=42))
        detection_bar = 50
        df["yolo_pattern"] = None
        df["yolo_confidence"] = 0.0
        df.iloc[detection_bar, df.columns.get_loc("yolo_pattern")] = "bull_flag"
        df.iloc[detection_bar, df.columns.get_loc("yolo_confidence")] = 0.50  # below 0.7

        result = YOLOPatternStrategy(
            pattern_names=["bull_flag"], min_confidence=0.7
        ).generate_signals(df)

        assert not result.entries.any(), (
            "Detection with confidence 0.50 below threshold 0.70 should not produce an entry"
        )

    def test_wrong_pattern_name_skipped(self) -> None:
        """A detection whose pattern is not in pattern_names must be skipped."""
        from app.backtesting.strategies.pattern_strategies import YOLOPatternStrategy

        df = _enrich(gen_uptrend(bars=200, seed=42))
        detection_bar = 50
        df["yolo_pattern"] = None
        df["yolo_confidence"] = 0.0
        df.iloc[detection_bar, df.columns.get_loc("yolo_pattern")] = "descending_triangle"
        df.iloc[detection_bar, df.columns.get_loc("yolo_confidence")] = 0.90

        result = YOLOPatternStrategy(
            pattern_names=["bull_flag", "ascending_triangle"], min_confidence=0.7
        ).generate_signals(df)

        assert not result.entries.any(), (
            "descending_triangle is not in pattern_names; no entry should be produced"
        )


# ===========================================================================
# Test class: CustomStrategy — AND/OR logic and crosses_above operator
# ===========================================================================


@pytest.mark.unit
class TestCustomStrategy:
    """CustomStrategy must correctly combine rules with AND/OR and handle operators."""

    def _base_df(self) -> pd.DataFrame:
        return _enrich(gen_uptrend(bars=200, seed=42))

    def test_and_logic_requires_all_rules(self) -> None:
        """AND logic: entry only when all rules simultaneously satisfied."""
        from app.backtesting.strategies.custom_strategy import CustomStrategy

        # Two independent threshold rules — AND should be strictly subset of each individually
        config_and = {
            "entry_rules": [
                {"indicator": "rsi", "operator": ">", "value": 50},
                {"indicator": "adx", "operator": ">", "value": 20},
            ],
            "exit_rules": [],
            "rule_logic": "AND",
        }
        config_rsi_only = {
            "entry_rules": [
                {"indicator": "rsi", "operator": ">", "value": 50},
            ],
            "exit_rules": [],
            "rule_logic": "AND",
        }

        df_and = self._base_df()
        df_rsi = self._base_df()

        result_and = CustomStrategy(config=config_and).generate_signals(df_and)
        result_rsi = CustomStrategy(config=config_rsi_only).generate_signals(df_rsi)

        # AND result must be a subset of RSI-only result
        # (every bar with AND entry must also be a RSI-only entry)
        and_bars = set(np.where(result_and.entries)[0])
        rsi_bars = set(np.where(result_rsi.entries)[0])
        assert and_bars.issubset(rsi_bars), (
            "AND(RSI>50, ADX>20) produced entries at bars not in RSI>50 alone: "
            f"{and_bars - rsi_bars}"
        )

    def test_or_logic_is_superset_of_and_logic(self) -> None:
        """OR logic must produce >= as many entries as AND logic for the same rules."""
        from app.backtesting.strategies.custom_strategy import CustomStrategy

        rules = [
            {"indicator": "rsi", "operator": ">", "value": 50},
            {"indicator": "adx", "operator": ">", "value": 20},
        ]
        config_and = {"entry_rules": rules, "exit_rules": [], "rule_logic": "AND"}
        config_or = {"entry_rules": rules, "exit_rules": [], "rule_logic": "OR"}

        df_and = self._base_df()
        df_or = self._base_df()

        result_and = CustomStrategy(config=config_and).generate_signals(df_and)
        result_or = CustomStrategy(config=config_or).generate_signals(df_or)

        n_and = int(result_and.entries.sum())
        n_or = int(result_or.entries.sum())
        assert n_or >= n_and, (
            f"OR ({n_or} entries) should have >= entries than AND ({n_and} entries)"
        )

    def test_crosses_above_operator_produces_bool_length(self) -> None:
        """crosses_above operator must produce entries/exits of correct shape and dtype."""
        from app.backtesting.strategies.custom_strategy import CustomStrategy

        config = {
            "entry_rules": [
                {"indicator": "rsi", "operator": "crosses_above", "value": 50},
            ],
            "exit_rules": [
                {"indicator": "rsi", "operator": "crosses_above", "value": 70},
            ],
            "rule_logic": "AND",
        }
        df = self._base_df()
        result = CustomStrategy(config=config).generate_signals(df)

        assert len(result.entries) == len(df), "entries length mismatch"
        assert len(result.exits) == len(df), "exits length mismatch"
        assert result.entries.dtype == bool
        assert result.exits.dtype == bool

    def test_no_simultaneous_entry_and_exit_in_custom_strategy(self) -> None:
        """CustomStrategy explicitly prevents entry+exit on the same bar."""
        from app.backtesting.strategies.custom_strategy import CustomStrategy

        # Use RSI for both entry and exit — overlapping conditions are possible
        config = {
            "entry_rules": [
                {"indicator": "rsi", "operator": ">", "value": 45},
            ],
            "exit_rules": [
                {"indicator": "rsi", "operator": ">", "value": 50},
            ],
            "rule_logic": "OR",
        }
        df = self._base_df()
        result = CustomStrategy(config=config).generate_signals(df)

        simultaneous = result.entries & result.exits
        assert not simultaneous.any(), (
            f"CustomStrategy produced simultaneous entry+exit at bars: "
            f"{np.where(simultaneous)[0].tolist()}"
        )

    def test_empty_rules_produce_all_false(self) -> None:
        """No entry/exit rules must yield all-False arrays of correct length."""
        from app.backtesting.strategies.custom_strategy import CustomStrategy

        config = {"entry_rules": [], "exit_rules": [], "rule_logic": "AND"}
        df = self._base_df()
        result = CustomStrategy(config=config).generate_signals(df)

        assert not result.entries.any(), "Empty entry rules should yield no entries"
        assert not result.exits.any(), "Empty exit rules should yield no exits"
        assert len(result.entries) == len(df)
        assert len(result.exits) == len(df)

    def test_atr_stop_always_below_close(self) -> None:
        """When stop_type='atr', stop_prices must be below close at every bar."""
        from app.backtesting.strategies.custom_strategy import CustomStrategy

        config = {
            "entry_rules": [
                {"indicator": "rsi", "operator": ">", "value": 40},
            ],
            "exit_rules": [],
            "rule_logic": "AND",
            "stop_type": "atr",
            "stop_value": 2.0,
        }
        df = self._base_df()
        result = CustomStrategy(config=config).generate_signals(df)

        if result.stop_prices is not None:
            close = df["close"].to_numpy()
            finite_mask = np.isfinite(result.stop_prices)
            assert np.all(result.stop_prices[finite_mask] < close[finite_mask]), (
                "ATR-based stop_prices must be strictly below close at every bar"
            )
