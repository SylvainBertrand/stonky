"""
Unit tests for app/backtesting/parameter_sweep.py.

Tests cover:
- Grid size: a 3x3 param_space produces exactly 9 results
- Best result selection: the selected best has the highest value of the sweep metric
- Heatmap data: a 2x2 sweep produces exactly 4 heatmap entries with correct keys

All tests use gen_uptrend(bars=200, seed=42) — synthetic only, no DB/I/O.
"""

from __future__ import annotations

import pytest

from tests.generators import gen_uptrend


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ema_strategy(fast: int = 21, slow: int = 50):
    """Return an EMACrossoverStrategy with the given parameters."""
    from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

    return EMACrossoverStrategy(fast=fast, slow=slow)


def _make_sweep_config(strategy, metric: str = "sharpe_ratio", param_axes=None):
    """Return a SweepConfig for the given strategy."""
    from app.backtesting.parameter_sweep import SweepConfig

    return SweepConfig(
        strategy=strategy,
        param_axes=param_axes or ["fast", "slow"],
        metric=metric,
    )


# ===========================================================================
# Test class: grid size
# ===========================================================================


@pytest.mark.unit
class TestSweepGridSize:
    """run_sweep_sync must produce one BacktestResult per combination in param_space."""

    def test_3x3_grid_produces_9_results(self) -> None:
        """A strategy with 3 fast x 3 slow values must yield exactly 9 sweep results."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        # Override param_space to a deterministic 3x3 grid (small so the test is fast)
        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 12, 21]
        strategy.param_space["slow"] = [26, 50, 100]

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        assert len(sweep_result.results) == 9, (
            f"Expected 9 results from a 3x3 grid, got {len(sweep_result.results)}"
        )
        assert len(sweep_result.param_combos) == 9, (
            f"Expected 9 param combos from a 3x3 grid, got {len(sweep_result.param_combos)}"
        )

    def test_result_count_matches_cartesian_product(self) -> None:
        """Result count must equal the product of all param_space axis lengths."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 21]       # 2 values
        strategy.param_space["slow"] = [50, 100]     # 2 values
        # 2 x 2 = 4 combinations

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        assert len(sweep_result.results) == 4, (
            f"Expected 4 results (2x2 grid), got {len(sweep_result.results)}"
        )

    def test_all_param_combos_are_unique(self) -> None:
        """No two sweep runs should use the identical parameter combination."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 12, 21]
        strategy.param_space["slow"] = [26, 50, 100]

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        # Convert each combo dict to a frozenset-of-items for hashability
        combo_set = {frozenset(c.items()) for c in sweep_result.param_combos}
        assert len(combo_set) == len(sweep_result.param_combos), (
            "param_combos contains duplicate entries — grid product should be unique"
        )


# ===========================================================================
# Test class: best result selection
# ===========================================================================


@pytest.mark.unit
class TestBestResultSelection:
    """best_result must be the element with the highest value of the chosen metric."""

    def test_best_result_has_highest_sharpe(self) -> None:
        """best_result must be the BacktestResult with the highest sharpe_ratio."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 12, 21]
        strategy.param_space["slow"] = [26, 50, 100]

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        assert sweep_result.best_result is not None, "best_result must not be None"

        max_sharpe = max(r.sharpe_ratio for r in sweep_result.results)
        assert sweep_result.best_result.sharpe_ratio == max_sharpe, (
            f"best_result.sharpe_ratio={sweep_result.best_result.sharpe_ratio} but "
            f"the maximum across all results is {max_sharpe}"
        )

    def test_best_result_has_highest_total_return(self) -> None:
        """When metric='total_return_pct', best_result must have the highest total return."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 21]
        strategy.param_space["slow"] = [50, 100]

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="total_return_pct",
            ),
        )

        assert sweep_result.best_result is not None
        max_return = max(r.total_return_pct for r in sweep_result.results)
        assert sweep_result.best_result.total_return_pct == max_return, (
            f"best_result.total_return_pct={sweep_result.best_result.total_return_pct} "
            f"but max across all results is {max_return}"
        )

    def test_best_result_is_member_of_results_list(self) -> None:
        """best_result must be one of the objects in results (not a copy or new object)."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 21]
        strategy.param_space["slow"] = [50, 100]

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        assert sweep_result.best_result in sweep_result.results, (
            "best_result is not an element of the results list (identity check failed)"
        )


# ===========================================================================
# Test class: heatmap data
# ===========================================================================


@pytest.mark.unit
class TestHeatmapData:
    """Heatmap data must be populated with the correct number of entries."""

    def test_2x2_grid_produces_4_heatmap_entries(self) -> None:
        """A 2x2 parameter grid must produce exactly 4 entries in heatmap_data."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 21]    # 2 values
        strategy.param_space["slow"] = [50, 100]  # 2 values

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        # 2 fast values x 2 slow values = 4 heatmap cells
        assert len(sweep_result.heatmap_data) == 4, (
            f"Expected 4 heatmap entries for a 2x2 grid, got {len(sweep_result.heatmap_data)}"
        )

    def test_3x3_grid_produces_9_heatmap_entries(self) -> None:
        """A 3x3 parameter grid must produce exactly 9 entries in heatmap_data."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 12, 21]
        strategy.param_space["slow"] = [26, 50, 100]

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        assert len(sweep_result.heatmap_data) == 9, (
            f"Expected 9 heatmap entries for a 3x3 grid, got {len(sweep_result.heatmap_data)}"
        )

    def test_heatmap_keys_represent_param_axis_pairs(self) -> None:
        """Heatmap keys must be string representations of (ax1_value, ax2_value) tuples."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 21]
        strategy.param_space["slow"] = [50, 100]

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        # Keys should look like "(9, 50)", "(9, 100)", "(21, 50)", "(21, 100)"
        expected_keys = {
            str((fast, slow))
            for fast in [9, 21]
            for slow in [50, 100]
        }
        actual_keys = set(sweep_result.heatmap_data.keys())
        assert actual_keys == expected_keys, (
            f"Heatmap keys mismatch.\n  Expected: {expected_keys}\n  Got: {actual_keys}"
        )

    def test_heatmap_values_are_numeric(self) -> None:
        """All heatmap values must be finite floats (the metric value for each cell)."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy
        import math

        strategy = EMACrossoverStrategy()
        strategy.param_space["fast"] = [9, 21]
        strategy.param_space["slow"] = [50, 100]

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast", "slow"],
                metric="sharpe_ratio",
            ),
        )

        for key, value in sweep_result.heatmap_data.items():
            assert isinstance(value, (int, float)), (
                f"heatmap_data[{key!r}]={value!r} is not numeric"
            )
            # Sharpe can legitimately be 0.0 (no trades) but should not be NaN/Inf
            assert not math.isnan(value), (
                f"heatmap_data[{key!r}] is NaN"
            )

    def test_single_axis_sweep_produces_correct_heatmap_count(self) -> None:
        """A sweep with a single param_axis must produce heatmap entries equal to axis length."""
        from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy()
        # Restrict to one axis for this test — only vary fast
        strategy.param_space = {"fast": [9, 21, 50]}

        df = gen_uptrend(bars=200, seed=42)
        sweep_result = run_sweep_sync(
            df=df,
            sweep_config=SweepConfig(
                strategy=strategy,
                param_axes=["fast"],   # single-axis heatmap
                metric="sharpe_ratio",
            ),
        )

        assert len(sweep_result.results) == 3, (
            f"Expected 3 results for a single-axis sweep, got {len(sweep_result.results)}"
        )
        assert len(sweep_result.heatmap_data) == 3, (
            f"Expected 3 heatmap entries for a single-axis sweep, "
            f"got {len(sweep_result.heatmap_data)}"
        )
