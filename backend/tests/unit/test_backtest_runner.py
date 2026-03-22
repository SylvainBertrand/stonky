"""
Unit tests for app/backtesting/runner.py.

Tests cover:
- enrich_dataframe: indicator columns are added and original OHLCV data is preserved
- run_backtest_sync: result fields, commission impact, benchmark accuracy, equity curve shape

All tests use gen_uptrend(bars=200, seed=42) — synthetic only, no DB/I/O.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tests.generators import gen_uptrend


# ---------------------------------------------------------------------------
# enrich_dataframe
# ---------------------------------------------------------------------------


def _make_enriched_df(bars: int = 200, seed: int = 42) -> pd.DataFrame:
    """Return a DataFrame with the time column promoted to the DatetimeIndex and all
    indicator columns added via enrich_dataframe.

    The generators return a 'time' column as a plain column with RangeIndex.
    enrich_dataframe delegates to compute_*() functions that each return a new DataFrame
    (not in-place mutation), so we capture the return value and also set the index to
    satisfy compute_vwap()'s DatetimeIndex requirement — mirroring what pipeline.py does.
    """
    from app.backtesting.runner import enrich_dataframe

    df = gen_uptrend(bars=bars, seed=seed).set_index("time")
    return enrich_dataframe(df)


@pytest.mark.unit
class TestEnrichDataframe:
    """enrich_dataframe must add all expected indicator columns without corrupting OHLCV.

    NOTE: enrich_dataframe() returns an enriched DataFrame (it does not mutate the
    input in-place, since each compute_*() function returns a new copy). Always use
    the return value: `df = enrich_dataframe(df)`.
    """

    # Columns that downstream strategies depend on — all must be present after enrichment
    REQUIRED_COLUMNS = [
        "ema_21",
        "rsi_14",
        "adx",
        "atr",
        "macd",
        "obv",
        "cmf",
        "supertrend_dir",
    ]

    def test_adds_all_required_indicator_columns(self) -> None:
        """All indicator columns used by strategies must be present after enrichment.

        enrich_dataframe() returns the enriched DataFrame — the caller must capture
        the return value, as the underlying compute_*() functions each return new copies.
        """
        df = _make_enriched_df()

        missing = [col for col in self.REQUIRED_COLUMNS if col not in df.columns]
        assert not missing, (
            f"enrich_dataframe did not add the following expected columns: {missing}"
        )

    def test_preserves_original_ohlcv_values(self) -> None:
        """enrich_dataframe must not modify the open/high/low/close/volume values."""
        from app.backtesting.runner import enrich_dataframe

        raw = gen_uptrend(bars=200, seed=42).set_index("time")
        # Snapshot OHLCV before enrichment
        ohlcv_before = raw[["open", "high", "low", "close", "volume"]].copy()

        enriched = enrich_dataframe(raw.copy())

        pd.testing.assert_frame_equal(
            enriched[["open", "high", "low", "close", "volume"]],
            ohlcv_before,
            check_names=True,
            obj="OHLCV columns after enrich_dataframe",
        )

    def test_enriched_dataframe_row_count_unchanged(self) -> None:
        """Enrichment must not add or remove rows."""
        bars = 200
        df = _make_enriched_df(bars=bars)
        assert len(df) == bars, (
            f"enrich_dataframe changed row count from {bars} to {len(df)}"
        )

    def test_ema_21_column_has_numeric_values(self) -> None:
        """ema_21 must be numeric with no non-finite values after the EMA(21) warmup period."""
        df = _make_enriched_df()

        ema = df["ema_21"].to_numpy()
        # EMA(21) is fully computable by bar 21; check the last 100 bars are all finite
        tail = ema[-100:]
        assert np.all(np.isfinite(tail)), (
            "ema_21 has non-finite values in the last 100 bars of a 200-bar series"
        )

    def test_supertrend_dir_contains_only_plus_minus_one(self) -> None:
        """supertrend_dir must be a binary signal: only +1 or -1 values after warmup."""
        df = _make_enriched_df()

        st_dir = df["supertrend_dir"].dropna().to_numpy()
        unique_vals = np.unique(st_dir)
        assert set(unique_vals).issubset({1, -1, 1.0, -1.0}), (
            f"supertrend_dir contains unexpected values: {unique_vals.tolist()}; "
            "expected only +1 and -1"
        )

    def test_harmonic_columns_added_by_enrichment(self) -> None:
        """enrich_dataframe must materialize harmonic detection columns via _materialize_harmonics."""
        df = _make_enriched_df()

        for col in ("harmonic_detected", "harmonic_score", "harmonic_prz_low",
                    "harmonic_prz_high", "harmonic_x_price"):
            assert col in df.columns, (
                f"Column '{col}' missing — enrich_dataframe must call _materialize_harmonics"
            )


# ---------------------------------------------------------------------------
# run_backtest_sync
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRunBacktestSync:
    """run_backtest_sync must return a well-structured BacktestResult with plausible values."""

    def _make_result(self, commission_pct: float = 0.001):
        """Run a default backtest and return the result."""
        from app.backtesting.runner import run_backtest_sync
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        df = gen_uptrend(bars=200, seed=42)
        return run_backtest_sync(
            df=df,
            strategy=EMACrossoverStrategy(),
            initial_capital=10_000.0,
            commission_pct=commission_pct,
            slippage_pct=0.0005,
        )

    def test_returns_backtest_result_instance(self) -> None:
        """run_backtest_sync must return a BacktestResult dataclass."""
        from app.backtesting.results import BacktestResult

        result = self._make_result()
        assert isinstance(result, BacktestResult)

    def test_all_scalar_fields_present(self) -> None:
        """Core scalar fields must all be present and of numeric type."""
        result = self._make_result()
        scalar_fields = [
            "total_return_pct",
            "cagr_pct",
            "sharpe_ratio",
            "sortino_ratio",
            "max_drawdown_pct",
            "max_drawdown_duration_days",
            "win_rate_pct",
            "profit_factor",
            "total_trades",
            "avg_trade_pct",
            "avg_win_pct",
            "avg_loss_pct",
            "benchmark_return_pct",
            "benchmark_sharpe",
        ]
        for field_name in scalar_fields:
            val = getattr(result, field_name)
            assert val is not None, f"BacktestResult.{field_name} is None"
            assert isinstance(val, (int, float)), (
                f"BacktestResult.{field_name}={val!r} is not numeric"
            )

    def test_equity_curve_length_equals_dataframe_length(self) -> None:
        """Equity curve must contain one entry per bar of the input DataFrame."""
        from app.backtesting.runner import run_backtest_sync
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        bars = 200
        df = gen_uptrend(bars=bars, seed=42)
        result = run_backtest_sync(df=df, strategy=EMACrossoverStrategy())

        assert len(result.equity_curve) == bars, (
            f"equity_curve has {len(result.equity_curve)} entries for a {bars}-bar DataFrame"
        )

    def test_drawdown_curve_length_equals_dataframe_length(self) -> None:
        """Drawdown curve must have the same length as the input DataFrame."""
        from app.backtesting.runner import run_backtest_sync
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        bars = 200
        df = gen_uptrend(bars=bars, seed=42)
        result = run_backtest_sync(df=df, strategy=EMACrossoverStrategy())

        assert len(result.drawdown_curve) == bars, (
            f"drawdown_curve has {len(result.drawdown_curve)} entries for a {bars}-bar DataFrame"
        )

    def test_equity_curve_entries_have_date_and_value_keys(self) -> None:
        """Each equity curve dict must have 'date' and 'value' keys."""
        result = self._make_result()
        for i, entry in enumerate(result.equity_curve[:5]):
            assert "date" in entry, f"equity_curve[{i}] missing 'date' key"
            assert "value" in entry, f"equity_curve[{i}] missing 'value' key"

    def test_commission_affects_total_return_when_trades_occur(self) -> None:
        """Higher commission must produce a lower (or equal) total return than zero commission.

        If the strategy generates at least one trade, commission drag must reduce returns.
        If no trades occur, total_return_pct will be the same (both zero) — test skips gracefully.
        """
        result_zero_commission = self._make_result(commission_pct=0.0)
        result_high_commission = self._make_result(commission_pct=0.01)  # 1%

        if result_zero_commission.total_trades == 0:
            pytest.skip(
                "EMACrossoverStrategy produced no trades on this uptrend dataset; "
                "cannot compare commission impact without trades"
            )

        assert result_high_commission.total_return_pct <= result_zero_commission.total_return_pct, (
            f"1% commission ({result_high_commission.total_return_pct}%) should reduce return "
            f"vs 0% commission ({result_zero_commission.total_return_pct}%)"
        )

    def test_benchmark_return_matches_buy_and_hold(self) -> None:
        """benchmark_return_pct must match the manual buy-and-hold calculation within 0.1%."""
        from app.backtesting.runner import run_backtest_sync
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        df = gen_uptrend(bars=200, seed=42)
        # Capture first/last close before enrichment mutates the df
        first_close = float(df["close"].iloc[0])
        last_close = float(df["close"].iloc[-1])

        result = run_backtest_sync(df=df, strategy=EMACrossoverStrategy())

        expected_bh_return = (last_close / first_close - 1) * 100
        assert abs(result.benchmark_return_pct - expected_bh_return) <= 0.1, (
            f"benchmark_return_pct={result.benchmark_return_pct:.4f}% does not match "
            f"manual buy-and-hold={expected_bh_return:.4f}% (tolerance 0.1%)"
        )

    def test_win_rate_is_between_0_and_100(self) -> None:
        """win_rate_pct must be in [0, 100] regardless of market regime."""
        result = self._make_result()
        assert 0.0 <= result.win_rate_pct <= 100.0, (
            f"win_rate_pct={result.win_rate_pct} is outside [0, 100]"
        )

    def test_max_drawdown_is_non_positive(self) -> None:
        """max_drawdown_pct must be <= 0 (drawdown is a loss measure, stored as negative pct)."""
        result = self._make_result()
        assert result.max_drawdown_pct <= 0.0, (
            f"max_drawdown_pct={result.max_drawdown_pct} is positive; "
            "drawdown must be expressed as a non-positive percentage"
        )

    def test_initial_equity_curve_value_equals_initial_capital(self) -> None:
        """The first entry in the equity curve must equal the initial capital."""
        result = self._make_result()
        first_value = result.equity_curve[0]["value"]
        assert abs(first_value - 10_000.0) < 1.0, (
            f"First equity curve value {first_value} does not match initial capital 10000.0"
        )

    def test_config_fields_recorded_correctly(self) -> None:
        """BacktestConfig inside result must record the exact strategy name and parameters."""
        from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy

        strategy = EMACrossoverStrategy(fast=9, slow=26)
        from app.backtesting.runner import run_backtest_sync

        df = gen_uptrend(bars=200, seed=42)
        result = run_backtest_sync(df=df, strategy=strategy)

        assert result.config.strategy_name == "ema_crossover"
        assert result.config.strategy_params["fast"] == 9
        assert result.config.strategy_params["slow"] == 26

    def test_trades_list_entries_have_required_keys(self) -> None:
        """Each trade dict must include entry/exit price, bar, date, pnl, and direction."""
        result = self._make_result()
        if not result.trades:
            pytest.skip("No trades to validate trade log structure")

        required_keys = {
            "entry_bar", "exit_bar", "entry_price", "exit_price",
            "pnl_pct", "pnl_abs", "direction", "entry_date", "exit_date",
        }
        for i, trade in enumerate(result.trades):
            missing = required_keys - set(trade.keys())
            assert not missing, (
                f"Trade {i} is missing keys: {missing}"
            )

    def test_profit_factor_is_non_negative(self) -> None:
        """profit_factor must be >= 0. It is undefined (set to 0) when there are no losing trades."""
        result = self._make_result()
        assert result.profit_factor >= 0.0, (
            f"profit_factor={result.profit_factor} is negative"
        )
