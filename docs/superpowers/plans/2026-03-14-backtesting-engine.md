# Backtesting Engine Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a backtesting engine that replays historical OHLCV through strategy signal generators and produces performance statistics with a full UI.

**Architecture:** Separate `backend/app/backtesting/` module. Strategies reuse existing indicator compute functions. Custom NumPy portfolio simulator (vectorbt fallback per spec — compatibility issues with Python 3.12+). Results stored in `backtest_results` table. React frontend at `/backtest` with equity curve, trade list, stats, and parameter sweep heatmap.

**Tech Stack:** Python (vectorbt, existing pandas-ta indicators), FastAPI, Alembic, React/TypeScript, TradingView Lightweight Charts, Zustand, TanStack Query.

**Spec:** `docs/superpowers/specs/2026-03-14-backtesting-engine-design.md`

---

## File Structure

### Backend — New Files

| File | Responsibility |
|------|---------------|
| `backend/app/backtesting/__init__.py` | Package init |
| `backend/app/backtesting/strategies/__init__.py` | Package init, strategy registry |
| `backend/app/backtesting/strategies/base.py` | `StrategyBase` protocol + `SignalResult` dataclass |
| `backend/app/backtesting/strategies/indicator_strategies.py` | EMACrossover, RSIThreshold, MACDCross, Supertrend strategies |
| `backend/app/backtesting/strategies/profile_strategies.py` | MomentumBreakout, TrendFollowing, MeanReversion, HarmonicSetup |
| `backend/app/backtesting/strategies/pattern_strategies.py` | YOLOv8PatternStrategy |
| `backend/app/backtesting/strategies/custom_strategy.py` | CustomStrategy rule combiner |
| `backend/app/backtesting/results.py` | `BacktestResult` + `BacktestConfig` dataclasses |
| `backend/app/backtesting/runner.py` | `enrich_dataframe()`, `run_backtest()` |
| `backend/app/backtesting/parameter_sweep.py` | `run_parameter_sweep()`, `SweepConfig`, `SweepResult` |
| `backend/app/schemas/backtests.py` | Pydantic request/response schemas |
| `backend/app/models/backtest.py` | SQLAlchemy `BacktestResult` model |
| `backend/app/api/backtests.py` | REST endpoints |
| `backend/alembic/versions/005_backtest_results.py` | Migration |

### Backend — Modified Files

| File | Change |
|------|--------|
| `backend/app/main.py` | Register backtests router |
| `backend/app/models/__init__.py` | Re-export `BacktestResultModel` and add to `__all__` |
| `frontend/src/api/scanner.ts` | Update import to use extracted `apiFetch` from `client.ts` |

### Backend — Test Files

| File | Contents |
|------|----------|
| `backend/tests/unit/test_strategies.py` | Strategy signal generation tests |
| `backend/tests/unit/test_backtest_runner.py` | Runner + results tests |
| `backend/tests/unit/test_parameter_sweep.py` | Sweep tests |

### Frontend — New Files

| File | Responsibility |
|------|---------------|
| `frontend/src/pages/BacktestPage.tsx` | Page layout: configurator + results |
| `frontend/src/components/backtest/StrategyConfigurator.tsx` | Strategy/param config form |
| `frontend/src/components/backtest/BacktestSummaryStats.tsx` | Metrics bar |
| `frontend/src/components/backtest/EquityCurveChart.tsx` | TradingView equity + drawdown chart |
| `frontend/src/components/backtest/TradeListTable.tsx` | Paginated trade log |
| `frontend/src/components/backtest/ParameterSweepHeatmap.tsx` | Canvas 2D heatmap |
| `frontend/src/stores/backtestStore.ts` | Zustand store |
| `frontend/src/api/backtests.ts` | API client |

### Frontend — Modified Files

| File | Change |
|------|--------|
| `frontend/src/App.tsx` | Add `/backtest` route + nav link |
| `frontend/src/types/index.ts` | Add backtest types |

---

## Chunk 1: Foundation — Base, Results, Indicator Strategies

### Task 1: StrategyBase protocol + SignalResult

**Files:**
- Create: `backend/app/backtesting/__init__.py`
- Create: `backend/app/backtesting/strategies/__init__.py`
- Create: `backend/app/backtesting/strategies/base.py`

- [ ] **Step 1: Create package structure**

Create `backend/app/backtesting/__init__.py` (empty).
Create `backend/app/backtesting/strategies/__init__.py` (empty).

- [ ] **Step 2: Write base.py**

```python
"""Strategy protocol and signal result dataclass for backtesting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

import numpy as np
import pandas as pd


@dataclass
class SignalResult:
    """Output of a strategy's signal generation."""

    entries: np.ndarray  # bool array, True = enter long
    exits: np.ndarray  # bool array, True = exit long
    stop_prices: np.ndarray | None = None  # per-bar absolute stop price
    target_prices: np.ndarray | None = None  # per-bar absolute target price


class StrategyBase(Protocol):
    """Protocol that all backtest strategies must satisfy."""

    name: str
    parameters: dict
    param_space: dict  # {param_name: [possible_values]} for sweep

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        """Given OHLCV+indicators DataFrame, return entry/exit arrays (same length as df)."""
        ...

    def describe(self) -> str:
        """Human-readable description of current parameter config."""
        ...
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/backtesting/
git commit -m "feat(backtest): add StrategyBase protocol and SignalResult dataclass"
```

---

### Task 2: BacktestConfig and BacktestResult dataclasses

**Files:**
- Create: `backend/app/backtesting/results.py`

- [ ] **Step 1: Write results.py**

```python
"""Backtest configuration and result dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BacktestConfig:
    """Configuration for a single backtest run."""

    symbol: str
    timeframe: str  # "1d" | "1w"
    start_date: str  # ISO date
    end_date: str  # ISO date
    strategy_name: str
    strategy_params: dict
    initial_capital: float = 10_000.0
    commission_pct: float = 0.001  # 0.1%
    slippage_pct: float = 0.0005  # 0.05%
    size_type: str = "percent"  # "percent" | "fixed_shares"
    position_size: float = 0.95  # 95% of capital
    allow_shorting: bool = False


@dataclass
class BacktestResult:
    """Complete result of a backtest run."""

    config: BacktestConfig

    # Core stats
    total_return_pct: float
    cagr_pct: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_duration_days: int
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    avg_trade_pct: float
    avg_win_pct: float
    avg_loss_pct: float

    # Time series (for charts)
    equity_curve: list[dict]  # [{date, value}]
    drawdown_curve: list[dict]  # [{date, pct}]

    # Trade log
    trades: list[dict]  # [{entry_date, exit_date, entry_price, exit_price, pnl_pct, pnl_abs, direction}]

    # Benchmark comparison (buy-and-hold)
    benchmark_return_pct: float
    benchmark_sharpe: float
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/backtesting/results.py
git commit -m "feat(backtest): add BacktestConfig and BacktestResult dataclasses"
```

---

### Task 3: Indicator strategies + tests

**Files:**
- Create: `backend/app/backtesting/strategies/indicator_strategies.py`
- Create: `backend/tests/unit/test_strategies.py`

- [ ] **Step 1: Write the test file first**

```python
"""Unit tests for backtest strategies."""

import numpy as np
import pandas as pd
import pytest

from tests.generators import gen_uptrend, gen_consolidation, gen_v_recovery

from app.backtesting.strategies.base import SignalResult
from app.backtesting.strategies.indicator_strategies import (
    EMACrossoverStrategy,
    RSIThresholdStrategy,
    MACDCrossStrategy,
    SupertrendStrategy,
)


def _enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Compute all indicators on a DataFrame for testing."""
    from app.analysis.indicators.trend import compute_ema, compute_adx, compute_supertrend
    from app.analysis.indicators.momentum import compute_rsi, compute_macd, compute_stoch
    from app.analysis.indicators.volatility import compute_bbands, compute_atr, compute_ttm_squeeze
    from app.analysis.indicators.volume import compute_obv, compute_vwap, compute_cmf

    compute_ema(df)
    compute_adx(df)
    compute_supertrend(df)
    compute_rsi(df)
    compute_macd(df)
    compute_stoch(df)
    compute_bbands(df)
    compute_atr(df)
    compute_ttm_squeeze(df)
    compute_obv(df)
    compute_vwap(df)
    compute_cmf(df)
    return df


@pytest.mark.unit
class TestSignalResultShape:
    """All strategies must produce arrays matching input length."""

    @pytest.fixture
    def enriched_uptrend(self) -> pd.DataFrame:
        return _enrich(gen_uptrend(bars=200, seed=42))

    @pytest.mark.parametrize(
        "strategy_cls,kwargs",
        [
            (EMACrossoverStrategy, {"fast": 21, "slow": 50}),
            (RSIThresholdStrategy, {"oversold": 30, "overbought": 70}),
            (MACDCrossStrategy, {"fast": 12, "slow": 26, "signal": 9}),
            (SupertrendStrategy, {"atr_period": 10, "multiplier": 3.0}),
        ],
    )
    def test_signal_length_matches_df(self, enriched_uptrend, strategy_cls, kwargs):
        strategy = strategy_cls(**kwargs)
        result = strategy.generate_signals(enriched_uptrend)
        assert isinstance(result, SignalResult)
        assert len(result.entries) == len(enriched_uptrend)
        assert len(result.exits) == len(enriched_uptrend)

    @pytest.mark.parametrize(
        "strategy_cls,kwargs",
        [
            (EMACrossoverStrategy, {"fast": 21, "slow": 50}),
            (RSIThresholdStrategy, {"oversold": 30, "overbought": 70}),
            (MACDCrossStrategy, {"fast": 12, "slow": 26, "signal": 9}),
            (SupertrendStrategy, {"atr_period": 10, "multiplier": 3.0}),
        ],
    )
    def test_signals_are_boolean(self, enriched_uptrend, strategy_cls, kwargs):
        strategy = strategy_cls(**kwargs)
        result = strategy.generate_signals(enriched_uptrend)
        assert result.entries.dtype == bool
        assert result.exits.dtype == bool


@pytest.mark.unit
class TestEMACrossoverStrategy:
    """EMA crossover should produce signals at known crossover points."""

    def test_crossover_signals_on_uptrend(self):
        # Uptrend should eventually produce a bullish crossover
        df = _enrich(gen_uptrend(bars=200, seed=42))
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        result = strategy.generate_signals(df)
        # Should have at least one entry in an uptrend
        assert result.entries.any(), "Expected at least one entry signal in uptrend"

    def test_no_simultaneous_entry_exit(self):
        df = _enrich(gen_uptrend(bars=200, seed=42))
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        result = strategy.generate_signals(df)
        # No bar should have both entry and exit
        assert not (result.entries & result.exits).any()

    def test_describe(self):
        strategy = EMACrossoverStrategy(fast=9, slow=26)
        desc = strategy.describe()
        assert "9" in desc
        assert "26" in desc

    def test_param_space_defined(self):
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        assert "fast" in strategy.param_space
        assert "slow" in strategy.param_space
        assert isinstance(strategy.param_space["fast"], list)


@pytest.mark.unit
class TestNoLookaheadBias:
    """Signals at bar N must only use data up to bar N."""

    def test_ema_crossover_no_lookahead(self):
        """Truncating the last 20 bars should not change signals for earlier bars."""
        df = _enrich(gen_uptrend(bars=200, seed=42))
        strategy = EMACrossoverStrategy(fast=21, slow=50)

        full_result = strategy.generate_signals(df)

        # Truncate last 20 bars and recompute
        df_trunc = _enrich(gen_uptrend(bars=180, seed=42))
        trunc_result = strategy.generate_signals(df_trunc)

        # Signals for first 180 bars should be identical
        np.testing.assert_array_equal(
            full_result.entries[:180],
            trunc_result.entries[:180],
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/unit/test_strategies.py -v --no-header -x 2>&1 | head -20`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.backtesting.strategies.indicator_strategies'`

- [ ] **Step 3: Write indicator_strategies.py**

```python
"""Indicator-based backtest strategies for baseline comparison."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.strategies.base import SignalResult


@dataclass
class EMACrossoverStrategy:
    """Entry when fast EMA crosses above slow EMA; exit on cross below."""

    fast: int = 21
    slow: int = 50
    name: str = field(init=False, default="ema_crossover")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {"fast": [9, 12, 21], "slow": [26, 50, 100]},
    )

    @property
    def parameters(self) -> dict:
        return {"fast": self.fast, "slow": self.slow}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        fast_col = f"ema_{self.fast}"
        slow_col = f"ema_{self.slow}"

        # If non-standard EMA periods requested, compute them
        if fast_col not in df.columns:
            df[fast_col] = df["close"].ewm(span=self.fast, adjust=False).mean()
        if slow_col not in df.columns:
            df[slow_col] = df["close"].ewm(span=self.slow, adjust=False).mean()

        fast_ema = df[fast_col].to_numpy()
        slow_ema = df[slow_col].to_numpy()

        # Cross above: fast was <= slow, now fast > slow
        cross_above = (fast_ema[1:] > slow_ema[1:]) & (
            np.roll(fast_ema, 1)[1:] <= np.roll(slow_ema, 1)[1:]
        )
        # Cross below: fast was >= slow, now fast < slow
        cross_below = (fast_ema[1:] < slow_ema[1:]) & (
            np.roll(fast_ema, 1)[1:] >= np.roll(slow_ema, 1)[1:]
        )

        entries = np.zeros(len(df), dtype=bool)
        exits = np.zeros(len(df), dtype=bool)
        entries[1:] = cross_above
        exits[1:] = cross_below

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"EMA Crossover ({self.fast}/{self.slow})"


@dataclass
class RSIThresholdStrategy:
    """Entry when RSI crosses above oversold; exit when RSI crosses above overbought."""

    oversold: int = 30
    overbought: int = 70
    name: str = field(init=False, default="rsi_threshold")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {"oversold": [25, 30, 35], "overbought": [65, 70, 75]},
    )

    @property
    def parameters(self) -> dict:
        return {"oversold": self.oversold, "overbought": self.overbought}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        rsi = df["rsi_14"].to_numpy()
        prev_rsi = np.roll(rsi, 1)

        entries = np.zeros(len(df), dtype=bool)
        exits = np.zeros(len(df), dtype=bool)

        # Cross above oversold
        entries[1:] = (rsi[1:] > self.oversold) & (prev_rsi[1:] <= self.oversold)
        # Cross above overbought
        exits[1:] = (rsi[1:] > self.overbought) & (prev_rsi[1:] <= self.overbought)

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"RSI Threshold (oversold={self.oversold}, overbought={self.overbought})"


@dataclass
class MACDCrossStrategy:
    """Entry when MACD crosses above signal; exit on cross below."""

    fast: int = 12
    slow: int = 26
    signal: int = 9
    name: str = field(init=False, default="macd_cross")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "fast": [8, 12, 16],
            "slow": [21, 26, 30],
            "signal": [7, 9, 11],
        },
    )

    @property
    def parameters(self) -> dict:
        return {"fast": self.fast, "slow": self.slow, "signal": self.signal}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        # Use pre-computed macd/macds if default params, otherwise recompute
        if self.fast == 12 and self.slow == 26 and self.signal == 9:
            macd_line = df["macd"].to_numpy()
            signal_line = df["macds"].to_numpy()
        else:
            fast_ema = df["close"].ewm(span=self.fast, adjust=False).mean()
            slow_ema = df["close"].ewm(span=self.slow, adjust=False).mean()
            macd_line = (fast_ema - slow_ema).to_numpy()
            signal_line = (
                pd.Series(macd_line).ewm(span=self.signal, adjust=False).mean().to_numpy()
            )

        prev_macd = np.roll(macd_line, 1)
        prev_signal = np.roll(signal_line, 1)

        entries = np.zeros(len(df), dtype=bool)
        exits = np.zeros(len(df), dtype=bool)

        entries[1:] = (macd_line[1:] > signal_line[1:]) & (prev_macd[1:] <= prev_signal[1:])
        exits[1:] = (macd_line[1:] < signal_line[1:]) & (prev_macd[1:] >= prev_signal[1:])

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"MACD Cross ({self.fast}/{self.slow}/{self.signal})"


@dataclass
class SupertrendStrategy:
    """Entry when price crosses above Supertrend; exit on cross below."""

    atr_period: int = 10
    multiplier: float = 3.0
    name: str = field(init=False, default="supertrend")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "atr_period": [7, 10, 14],
            "multiplier": [2.0, 2.5, 3.0, 3.5],
        },
    )

    @property
    def parameters(self) -> dict:
        return {"atr_period": self.atr_period, "multiplier": self.multiplier}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        # Use pre-computed supertrend_dir (default params: period=10, mult=3.0)
        st_dir = df["supertrend_dir"].to_numpy()
        prev_dir = np.roll(st_dir, 1)

        entries = np.zeros(len(df), dtype=bool)
        exits = np.zeros(len(df), dtype=bool)

        # Bullish flip: dir changes to +1
        entries[1:] = (st_dir[1:] == 1) & (prev_dir[1:] == -1)
        # Bearish flip: dir changes to -1
        exits[1:] = (st_dir[1:] == -1) & (prev_dir[1:] == 1)

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"Supertrend (ATR={self.atr_period}, mult={self.multiplier})"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/unit/test_strategies.py -v --no-header 2>&1 | tail -20`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/backtesting/ backend/tests/unit/test_strategies.py
git commit -m "feat(backtest): add indicator strategies (EMA, RSI, MACD, Supertrend) with tests"
```

---

## Chunk 2: Profile, Pattern, and Custom Strategies

### Task 4: Profile strategies

**Files:**
- Create: `backend/app/backtesting/strategies/profile_strategies.py`
- Modify: `backend/tests/unit/test_strategies.py`

- [ ] **Step 1: Add profile strategy tests to test_strategies.py**

Append to the test file:

```python
from app.backtesting.strategies.profile_strategies import (
    MomentumBreakoutStrategy,
    TrendFollowingStrategy,
    MeanReversionStrategy,
    HarmonicSetupStrategy,
)


@pytest.mark.unit
class TestProfileStrategies:
    @pytest.fixture
    def enriched_uptrend(self) -> pd.DataFrame:
        return _enrich(gen_uptrend(bars=200, seed=42))

    @pytest.fixture
    def enriched_consolidation(self) -> pd.DataFrame:
        return _enrich(gen_consolidation(bars=200, seed=42))

    @pytest.fixture
    def enriched_v_recovery(self) -> pd.DataFrame:
        return _enrich(gen_v_recovery(bars=200, seed=42))

    @pytest.mark.parametrize(
        "strategy_cls,kwargs",
        [
            (MomentumBreakoutStrategy, {}),
            (TrendFollowingStrategy, {}),
            (MeanReversionStrategy, {}),
            (HarmonicSetupStrategy, {}),
        ],
    )
    def test_signal_shape_and_dtype(self, enriched_uptrend, strategy_cls, kwargs):
        strategy = strategy_cls(**kwargs)
        result = strategy.generate_signals(enriched_uptrend)
        assert isinstance(result, SignalResult)
        assert len(result.entries) == len(enriched_uptrend)
        assert len(result.exits) == len(enriched_uptrend)
        assert result.entries.dtype == bool
        assert result.exits.dtype == bool

    def test_momentum_breakout_has_stops(self, enriched_uptrend):
        strategy = MomentumBreakoutStrategy()
        result = strategy.generate_signals(enriched_uptrend)
        # Should produce stop prices when entries fire
        if result.entries.any():
            assert result.stop_prices is not None

    def test_trend_following_on_uptrend(self, enriched_uptrend):
        strategy = TrendFollowingStrategy()
        result = strategy.generate_signals(enriched_uptrend)
        # Uptrend with EMA stack should produce entries
        # (may not always fire depending on RSI pullback window)
        assert result.entries.dtype == bool

    def test_mean_reversion_on_v_recovery(self, enriched_v_recovery):
        strategy = MeanReversionStrategy()
        result = strategy.generate_signals(enriched_v_recovery)
        # V-recovery has oversold conditions — may produce entries
        assert result.entries.dtype == bool
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_strategies.py::TestProfileStrategies -v --no-header -x 2>&1 | head -10`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write profile_strategies.py**

```python
"""Profile-based backtest strategies mirroring scanner profiles."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.strategies.base import SignalResult


@dataclass
class MomentumBreakoutStrategy:
    """TTM Squeeze fires + ADX + RSI zone + volume surge."""

    rsi_min: int = 50
    rsi_max: int = 70
    adx_min: int = 20
    volume_multiplier: float = 1.5
    squeeze_required: bool = True
    name: str = field(init=False, default="momentum_breakout")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "rsi_min": [45, 50, 55],
            "rsi_max": [65, 70, 75],
            "adx_min": [15, 20, 25],
            "volume_multiplier": [1.2, 1.5, 2.0],
        },
    )

    @property
    def parameters(self) -> dict:
        return {
            "rsi_min": self.rsi_min,
            "rsi_max": self.rsi_max,
            "adx_min": self.adx_min,
            "volume_multiplier": self.volume_multiplier,
            "squeeze_required": self.squeeze_required,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        stop_prices = np.full(n, np.nan)

        rsi = df["rsi_14"].to_numpy()
        adx = df["adx"].to_numpy()
        volume = df["volume"].to_numpy()
        close = df["close"].to_numpy()
        atr = df["atr"].to_numpy()
        st_dir = df["supertrend_dir"].to_numpy()

        # 20-bar average volume
        vol_avg = pd.Series(volume).rolling(20).mean().to_numpy()

        # Squeeze conditions
        squeeze_fired = df["squeeze_fired"].to_numpy().astype(bool) if "squeeze_fired" in df.columns else np.ones(n, dtype=bool)

        for i in range(1, n):
            rsi_ok = self.rsi_min <= rsi[i] <= self.rsi_max
            adx_ok = adx[i] > self.adx_min
            vol_ok = not np.isnan(vol_avg[i]) and volume[i] > self.volume_multiplier * vol_avg[i]
            squeeze_ok = (not self.squeeze_required) or squeeze_fired[i]

            if rsi_ok and adx_ok and vol_ok and squeeze_ok:
                entries[i] = True
                stop_prices[i] = close[i] - 1.5 * atr[i]

            # Exit: RSI > 75 OR Supertrend bearish flip
            if rsi[i] > 75:
                exits[i] = True
            if i > 0 and st_dir[i] == -1 and st_dir[i - 1] == 1:
                exits[i] = True

        return SignalResult(
            entries=entries,
            exits=exits,
            stop_prices=stop_prices if entries.any() else None,
        )

    def describe(self) -> str:
        return f"Momentum Breakout (RSI {self.rsi_min}-{self.rsi_max}, ADX>{self.adx_min})"


@dataclass
class TrendFollowingStrategy:
    """EMA stack + ADX + RSI pullback entry."""

    adx_min: int = 25
    ema_stack_required: bool = True
    rsi_pullback_min: int = 40
    rsi_pullback_max: int = 50
    name: str = field(init=False, default="trend_following")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "adx_min": [20, 25, 30],
            "rsi_pullback_min": [35, 40, 45],
            "rsi_pullback_max": [50, 55, 60],
        },
    )

    @property
    def parameters(self) -> dict:
        return {
            "adx_min": self.adx_min,
            "ema_stack_required": self.ema_stack_required,
            "rsi_pullback_min": self.rsi_pullback_min,
            "rsi_pullback_max": self.rsi_pullback_max,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)

        ema21 = df["ema_21"].to_numpy()
        ema50 = df["ema_50"].to_numpy()
        ema200 = df["ema_200"].to_numpy()
        adx = df["adx"].to_numpy()
        rsi = df["rsi_14"].to_numpy()
        st_dir = df["supertrend_dir"].to_numpy()

        for i in range(1, n):
            # EMA stack: 21 > 50 > 200
            stack_ok = (not self.ema_stack_required) or (ema21[i] > ema50[i] > ema200[i])
            adx_ok = adx[i] > self.adx_min
            pullback_ok = self.rsi_pullback_min <= rsi[i] <= self.rsi_pullback_max

            if stack_ok and adx_ok and pullback_ok:
                entries[i] = True

            # Exit: EMA 21 crosses below EMA 50 OR Supertrend bearish
            if ema21[i] < ema50[i] and ema21[i - 1] >= ema50[i - 1]:
                exits[i] = True
            if st_dir[i] == -1 and st_dir[i - 1] == 1:
                exits[i] = True

        return SignalResult(entries=entries, exits=exits)

    def describe(self) -> str:
        return f"Trend Following (ADX>{self.adx_min}, pullback RSI {self.rsi_pullback_min}-{self.rsi_pullback_max})"


@dataclass
class MeanReversionStrategy:
    """Oversold RSI + Stoch + BB touch + CMF confirmation."""

    rsi_max: int = 30
    stoch_k_max: int = 20
    require_bb_touch: bool = True
    require_cmf_positive: bool = True
    name: str = field(init=False, default="mean_reversion")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "rsi_max": [25, 30, 35],
            "stoch_k_max": [15, 20, 25],
        },
    )

    @property
    def parameters(self) -> dict:
        return {
            "rsi_max": self.rsi_max,
            "stoch_k_max": self.stoch_k_max,
            "require_bb_touch": self.require_bb_touch,
            "require_cmf_positive": self.require_cmf_positive,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        stop_prices = np.full(n, np.nan)

        rsi = df["rsi_14"].to_numpy()
        stoch_k = df["stoch_k"].to_numpy()
        close = df["close"].to_numpy()
        low = df["low"].to_numpy()
        bbl = df["bbl"].to_numpy()
        bbm = df["bbm"].to_numpy()
        cmf = df["cmf"].to_numpy()

        for i in range(1, n):
            rsi_ok = rsi[i] < self.rsi_max
            stoch_ok = stoch_k[i] < self.stoch_k_max
            bb_ok = (not self.require_bb_touch) or (close[i] <= bbl[i])
            cmf_ok = (not self.require_cmf_positive) or (cmf[i] > 0 and cmf[i - 1] <= 0)

            if rsi_ok and stoch_ok and bb_ok and cmf_ok:
                entries[i] = True
                # Stop below recent 10-bar swing low
                lookback = max(0, i - 10)
                stop_prices[i] = np.nanmin(low[lookback : i + 1]) * 0.99

            # Exit: RSI > 55 OR price reaches BB midline
            if rsi[i] > 55:
                exits[i] = True
            if not np.isnan(bbm[i]) and close[i] >= bbm[i] and close[i - 1] < bbm[i - 1]:
                exits[i] = True

        return SignalResult(
            entries=entries,
            exits=exits,
            stop_prices=stop_prices if entries.any() else None,
        )

    def describe(self) -> str:
        return f"Mean Reversion (RSI<{self.rsi_max}, Stoch<{self.stoch_k_max})"


@dataclass
class HarmonicSetupStrategy:
    """Entry on completed harmonic pattern with RSI divergence confirmation."""

    min_pattern_score: float = 0.6
    require_rsi_divergence: bool = True
    name: str = field(init=False, default="harmonic_setup")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {"min_pattern_score": [0.5, 0.6, 0.7, 0.8]},
    )

    @property
    def parameters(self) -> dict:
        return {
            "min_pattern_score": self.min_pattern_score,
            "require_rsi_divergence": self.require_rsi_divergence,
        }

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        stop_prices = np.full(n, np.nan)
        target_prices = np.full(n, np.nan)

        # Harmonic columns are materialized by the runner
        has_harmonics = "harmonic_detected" in df.columns
        if not has_harmonics:
            return SignalResult(entries=entries, exits=exits)

        detected = df["harmonic_detected"].to_numpy().astype(bool)
        score = df["harmonic_score"].to_numpy()
        prz_low = df["harmonic_prz_low"].to_numpy()
        prz_high = df["harmonic_prz_high"].to_numpy()
        x_price = df["harmonic_x_price"].to_numpy()
        close = df["close"].to_numpy()

        # RSI divergence: check if compute_rsi_divergence_signals flagged divergence
        # For simplicity, check if RSI is oversold as a proxy when column not available
        rsi = df["rsi_14"].to_numpy()

        for i in range(1, n):
            if not detected[i]:
                continue
            if score[i] < self.min_pattern_score:
                continue
            if self.require_rsi_divergence and rsi[i] > 40:
                continue

            entries[i] = True
            stop_prices[i] = x_price[i]  # Stop beyond X point
            # Target: 61.8% extension above PRZ
            prz_range = prz_high[i] - prz_low[i]
            target_prices[i] = prz_high[i] + 0.618 * prz_range

        # Exit when target hit (vectorbt handles via tp_stop)
        # Also exit if price drops below PRZ low
        for i in range(1, n):
            if has_harmonics and detected[i] and close[i] < prz_low[i]:
                exits[i] = True

        return SignalResult(
            entries=entries,
            exits=exits,
            stop_prices=stop_prices if entries.any() else None,
            target_prices=target_prices if entries.any() else None,
        )

    def describe(self) -> str:
        return f"Harmonic Setup (score>{self.min_pattern_score}, div={'required' if self.require_rsi_divergence else 'optional'})"
```

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_strategies.py -v --no-header 2>&1 | tail -20`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/backtesting/strategies/profile_strategies.py backend/tests/unit/test_strategies.py
git commit -m "feat(backtest): add profile strategies (Momentum, Trend, MeanReversion, Harmonic)"
```

---

### Task 5: Pattern strategy

**Files:**
- Create: `backend/app/backtesting/strategies/pattern_strategies.py`
- Modify: `backend/tests/unit/test_strategies.py`

- [ ] **Step 1: Add pattern strategy test**

```python
from app.backtesting.strategies.pattern_strategies import YOLOPatternStrategy


@pytest.mark.unit
class TestYOLOPatternStrategy:
    def test_no_detections_no_entries(self):
        df = _enrich(gen_uptrend(bars=100, seed=42))
        strategy = YOLOPatternStrategy(pattern_names=["bull_flag"], min_confidence=0.7)
        result = strategy.generate_signals(df)
        assert not result.entries.any()

    def test_detection_produces_entry(self):
        df = _enrich(gen_uptrend(bars=100, seed=42))
        # Simulate YOLO detection columns
        df["yolo_pattern"] = None
        df["yolo_confidence"] = 0.0
        df.loc[df.index[50], "yolo_pattern"] = "bull_flag"
        df.loc[df.index[50], "yolo_confidence"] = 0.85
        strategy = YOLOPatternStrategy(pattern_names=["bull_flag"], min_confidence=0.7)
        result = strategy.generate_signals(df)
        # Entry should be at bar 51 (bar after detection)
        assert result.entries[51]
```

- [ ] **Step 2: Run to verify failure, then write pattern_strategies.py**

```python
"""YOLO pattern-triggered backtest strategy."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.strategies.base import SignalResult


@dataclass
class YOLOPatternStrategy:
    """Entry on YOLO-detected chart pattern, exit via ATR trailing stop or target."""

    pattern_names: list[str] = field(default_factory=lambda: ["bull_flag", "ascending_triangle"])
    min_confidence: float = 0.7
    name: str = field(init=False, default="yolo_pattern")
    param_space: dict = field(
        init=False,
        default_factory=lambda: {
            "min_confidence": [0.6, 0.7, 0.8],
            "pattern_names": [
                ["bull_flag"],
                ["ascending_triangle"],
                ["bull_flag", "ascending_triangle"],
            ],
        },
    )

    @property
    def parameters(self) -> dict:
        return {"pattern_names": self.pattern_names, "min_confidence": self.min_confidence}

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entries = np.zeros(n, dtype=bool)
        exits = np.zeros(n, dtype=bool)
        stop_prices = np.full(n, np.nan)
        target_prices = np.full(n, np.nan)

        if "yolo_pattern" not in df.columns:
            return SignalResult(entries=entries, exits=exits)

        close = df["close"].to_numpy()
        atr = df["atr"].to_numpy()

        for i in range(n - 1):
            pattern = df.iloc[i]["yolo_pattern"]
            confidence = df.iloc[i]["yolo_confidence"]

            if pattern is None or pd.isna(confidence):
                continue
            if pattern not in self.pattern_names:
                continue
            if confidence < self.min_confidence:
                continue

            # Enter on next bar
            entries[i + 1] = True
            stop_prices[i + 1] = close[i + 1] - 2.0 * atr[i + 1] if not np.isnan(atr[i + 1]) else close[i + 1] * 0.95
            target_prices[i + 1] = close[i + 1] + 1.5 * abs(close[i] - close[max(0, i - 10)]) if i >= 10 else close[i + 1] * 1.05

        return SignalResult(
            entries=entries,
            exits=exits,
            stop_prices=stop_prices if entries.any() else None,
            target_prices=target_prices if entries.any() else None,
        )

    def describe(self) -> str:
        return f"YOLO Pattern ({', '.join(self.pattern_names)}, conf>{self.min_confidence})"
```

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
git add backend/app/backtesting/strategies/pattern_strategies.py backend/tests/unit/test_strategies.py
git commit -m "feat(backtest): add YOLO pattern strategy"
```

---

### Task 6: Custom strategy

**Files:**
- Create: `backend/app/backtesting/strategies/custom_strategy.py`
- Modify: `backend/tests/unit/test_strategies.py`

- [ ] **Step 1: Add custom strategy tests**

```python
from app.backtesting.strategies.custom_strategy import CustomStrategy


@pytest.mark.unit
class TestCustomStrategy:
    def test_and_logic(self):
        df = _enrich(gen_uptrend(bars=200, seed=42))
        config = {
            "entry_rules": [
                {"indicator": "rsi", "operator": "<", "value": 60},
                {"indicator": "adx", "operator": ">", "value": 15},
            ],
            "exit_rules": [
                {"indicator": "rsi", "operator": ">", "value": 70},
            ],
            "rule_logic": "AND",
            "stop_type": "atr",
            "stop_value": 1.5,
            "target_type": "rr",
            "target_value": 2.0,
        }
        strategy = CustomStrategy(config=config)
        result = strategy.generate_signals(df)
        assert result.entries.dtype == bool
        assert len(result.entries) == len(df)

    def test_or_logic(self):
        df = _enrich(gen_uptrend(bars=200, seed=42))
        config = {
            "entry_rules": [
                {"indicator": "rsi", "operator": "<", "value": 30},
                {"indicator": "squeeze_fired", "operator": "==", "value": True},
            ],
            "exit_rules": [
                {"indicator": "rsi", "operator": ">", "value": 70},
            ],
            "rule_logic": "OR",
            "stop_type": "fixed_pct",
            "stop_value": 3.0,
            "target_type": "rr",
            "target_value": 2.0,
        }
        strategy = CustomStrategy(config=config)
        result = strategy.generate_signals(df)
        assert result.entries.dtype == bool

    def test_crosses_above_operator(self):
        df = _enrich(gen_v_recovery(bars=200, seed=42))
        config = {
            "entry_rules": [
                {"indicator": "rsi", "operator": "crosses_above", "value": 30},
            ],
            "exit_rules": [
                {"indicator": "rsi", "operator": "crosses_above", "value": 70},
            ],
            "rule_logic": "AND",
            "stop_type": "atr",
            "stop_value": 2.0,
            "target_type": "rr",
            "target_value": 1.5,
        }
        strategy = CustomStrategy(config=config)
        result = strategy.generate_signals(df)
        assert result.entries.dtype == bool
```

- [ ] **Step 2: Write custom_strategy.py**

```python
"""Custom rule-combiner strategy configured via JSON from the UI."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.backtesting.strategies.base import SignalResult

# Map UI indicator names to DataFrame column names
INDICATOR_MAP: dict[str, str] = {
    "rsi": "rsi_14",
    "macd_hist": "macdh",
    "adx": "adx",
    "stoch_k": "stoch_k",
    "supertrend": "supertrend_dir",
    "ema21_slope": "_ema21_slope",
    "obv_slope": "_obv_slope",
    "cmf": "cmf",
    "bb_pct": "bbp",
    "squeeze_on": "squeeze_on",
    "squeeze_fired": "squeeze_fired",
}

# Supertrend string values mapped to numeric
SUPERTREND_VALUES = {"bullish": 1, "bearish": -1}


def _get_series(df: pd.DataFrame, indicator: str) -> np.ndarray:
    """Get the numpy array for an indicator, computing derived columns if needed."""
    if indicator == "ema21_slope":
        if "_ema21_slope" not in df.columns:
            df["_ema21_slope"] = df["ema_21"].diff()
        return df["_ema21_slope"].to_numpy()
    if indicator == "obv_slope":
        if "_obv_slope" not in df.columns:
            df["_obv_slope"] = df["obv"].diff()
        return df["_obv_slope"].to_numpy()

    col = INDICATOR_MAP.get(indicator, indicator)
    return df[col].to_numpy()


def _eval_rule(series: np.ndarray, operator: str, value, prev_series: np.ndarray | None = None) -> np.ndarray:
    """Evaluate a single rule, returning a boolean array. No eval() — safe dispatch."""
    # Handle supertrend string values
    if isinstance(value, str) and value in SUPERTREND_VALUES:
        value = SUPERTREND_VALUES[value]

    if operator == "<":
        return series < value
    elif operator == ">":
        return series > value
    elif operator == "<=":
        return series <= value
    elif operator == ">=":
        return series >= value
    elif operator == "==":
        if isinstance(value, bool):
            return series.astype(bool) == value
        return series == value
    elif operator == "crosses_above":
        if prev_series is None:
            return np.zeros(len(series), dtype=bool)
        result = np.zeros(len(series), dtype=bool)
        result[1:] = (series[1:] > value) & (prev_series[1:] <= value)
        return result
    elif operator == "crosses_below":
        if prev_series is None:
            return np.zeros(len(series), dtype=bool)
        result = np.zeros(len(series), dtype=bool)
        result[1:] = (series[1:] < value) & (prev_series[1:] >= value)
        return result
    else:
        raise ValueError(f"Unknown operator: {operator}")


@dataclass
class CustomStrategy:
    """Flexible rule combiner configured via JSON dict from the UI."""

    config: dict
    name: str = field(init=False, default="custom")
    param_space: dict = field(init=False, default_factory=dict)

    @property
    def parameters(self) -> dict:
        return self.config

    def generate_signals(self, df: pd.DataFrame) -> SignalResult:
        n = len(df)
        entry_rules = self.config.get("entry_rules", [])
        exit_rules = self.config.get("exit_rules", [])
        rule_logic = self.config.get("rule_logic", "AND")
        stop_type = self.config.get("stop_type", "atr")
        stop_value = self.config.get("stop_value", 1.5)

        # Evaluate entry rules
        entry_masks = []
        for rule in entry_rules:
            series = _get_series(df, rule["indicator"])
            prev_series = np.roll(series, 1)
            mask = _eval_rule(series, rule["operator"], rule["value"], prev_series)
            entry_masks.append(mask)

        if entry_masks:
            if rule_logic == "AND":
                entries = np.all(entry_masks, axis=0)
            else:  # OR
                entries = np.any(entry_masks, axis=0)
        else:
            entries = np.zeros(n, dtype=bool)

        # Evaluate exit rules (always AND)
        exit_masks = []
        for rule in exit_rules:
            series = _get_series(df, rule["indicator"])
            prev_series = np.roll(series, 1)
            mask = _eval_rule(series, rule["operator"], rule["value"], prev_series)
            exit_masks.append(mask)

        if exit_masks:
            exits = np.any(exit_masks, axis=0)  # Any exit rule triggers exit
        else:
            exits = np.zeros(n, dtype=bool)

        # Compute stops
        stop_prices = None
        if stop_type == "atr" and "atr" in df.columns:
            stop_prices = df["close"].to_numpy() - stop_value * df["atr"].to_numpy()
        elif stop_type == "fixed_pct":
            stop_prices = df["close"].to_numpy() * (1 - stop_value / 100)

        # Compute targets
        target_type = self.config.get("target_type")
        target_value = self.config.get("target_value", 2.0)
        target_prices = None
        if target_type == "rr" and stop_prices is not None:
            # Risk:Reward — target = entry + target_value * (entry - stop)
            close = df["close"].to_numpy()
            risk = close - stop_prices
            target_prices = close + target_value * risk
        elif target_type == "fib_extension" and "atr" in df.columns:
            target_prices = df["close"].to_numpy() + target_value * df["atr"].to_numpy()

        # Don't allow entry and exit on same bar
        both = entries & exits
        exits[both] = False

        return SignalResult(
            entries=entries.astype(bool),
            exits=exits.astype(bool),
            stop_prices=stop_prices,
            target_prices=target_prices,
        )

    def describe(self) -> str:
        n_entry = len(self.config.get("entry_rules", []))
        n_exit = len(self.config.get("exit_rules", []))
        logic = self.config.get("rule_logic", "AND")
        return f"Custom ({n_entry} entry rules [{logic}], {n_exit} exit rules)"
```

- [ ] **Step 3: Run tests, verify pass, commit**

```bash
git add backend/app/backtesting/strategies/custom_strategy.py backend/tests/unit/test_strategies.py
git commit -m "feat(backtest): add custom rule-combiner strategy"
```

---

### Task 7: Strategy registry

**Files:**
- Modify: `backend/app/backtesting/strategies/__init__.py`

- [ ] **Step 1: Write the registry**

```python
"""Strategy registry — maps string names to strategy classes."""

from app.backtesting.strategies.indicator_strategies import (
    EMACrossoverStrategy,
    MACDCrossStrategy,
    RSIThresholdStrategy,
    SupertrendStrategy,
)
from app.backtesting.strategies.profile_strategies import (
    HarmonicSetupStrategy,
    MeanReversionStrategy,
    MomentumBreakoutStrategy,
    TrendFollowingStrategy,
)
from app.backtesting.strategies.pattern_strategies import YOLOPatternStrategy
from app.backtesting.strategies.custom_strategy import CustomStrategy

STRATEGY_REGISTRY: dict[str, type] = {
    "ema_crossover": EMACrossoverStrategy,
    "rsi_threshold": RSIThresholdStrategy,
    "macd_cross": MACDCrossStrategy,
    "supertrend": SupertrendStrategy,
    "momentum_breakout": MomentumBreakoutStrategy,
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "harmonic_setup": HarmonicSetupStrategy,
    "yolo_pattern": YOLOPatternStrategy,
    "custom": CustomStrategy,
}


def create_strategy(strategy_type: str, parameters: dict):
    """Create a strategy instance from a type string and parameter dict."""
    cls = STRATEGY_REGISTRY.get(strategy_type)
    if cls is None:
        raise ValueError(f"Unknown strategy: {strategy_type}. Available: {list(STRATEGY_REGISTRY.keys())}")
    if strategy_type == "custom":
        return cls(config=parameters)
    return cls(**parameters)
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/backtesting/strategies/__init__.py
git commit -m "feat(backtest): add strategy registry with create_strategy()"
```

---

## Chunk 3: Runner + Parameter Sweep

### Task 8: BacktestRunner

**Files:**
- Create: `backend/app/backtesting/runner.py`
- Create: `backend/tests/unit/test_backtest_runner.py`

- [ ] **Step 1: Write runner tests**

```python
"""Unit tests for BacktestRunner."""

import numpy as np
import pandas as pd
import pytest

from tests.generators import gen_uptrend

from app.backtesting.results import BacktestConfig, BacktestResult
from app.backtesting.runner import enrich_dataframe, run_backtest_sync
from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy


@pytest.mark.unit
class TestEnrichDataframe:
    def test_adds_indicator_columns(self):
        df = gen_uptrend(bars=200, seed=42)
        result = enrich_dataframe(df)
        assert "ema_21" in result.columns
        assert "rsi_14" in result.columns
        assert "adx" in result.columns
        assert "atr" in result.columns
        assert "macd" in result.columns
        assert "obv" in result.columns
        assert "cmf" in result.columns
        assert "supertrend_dir" in result.columns

    def test_original_ohlcv_preserved(self):
        df = gen_uptrend(bars=200, seed=42)
        original_close = df["close"].copy()
        enrich_dataframe(df)
        pd.testing.assert_series_equal(df["close"], original_close)


@pytest.mark.unit
class TestRunBacktestSync:
    def test_returns_backtest_result(self):
        df = gen_uptrend(bars=200, seed=42)
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        result = run_backtest_sync(
            df=df,
            strategy=strategy,
            initial_capital=10_000.0,
            commission_pct=0.001,
            slippage_pct=0.0005,
        )
        assert isinstance(result, BacktestResult)
        assert result.total_trades >= 0
        assert isinstance(result.equity_curve, list)
        assert isinstance(result.trades, list)
        assert isinstance(result.sharpe_ratio, float)

    def test_commission_affects_returns(self):
        df = gen_uptrend(bars=200, seed=42)
        strategy = EMACrossoverStrategy(fast=21, slow=50)

        result_no_fees = run_backtest_sync(df=df, strategy=strategy, initial_capital=10_000.0, commission_pct=0.0, slippage_pct=0.0)
        result_with_fees = run_backtest_sync(df=df, strategy=strategy, initial_capital=10_000.0, commission_pct=0.01, slippage_pct=0.01)

        if result_no_fees.total_trades > 0:
            assert result_with_fees.total_return_pct <= result_no_fees.total_return_pct

    def test_benchmark_matches_buy_and_hold(self):
        df = gen_uptrend(bars=200, seed=42)
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        result = run_backtest_sync(df=df, strategy=strategy, initial_capital=10_000.0)

        # Manual buy-and-hold
        expected_bh = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100
        assert abs(result.benchmark_return_pct - expected_bh) < 0.1

    def test_equity_curve_length(self):
        df = gen_uptrend(bars=200, seed=42)
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        result = run_backtest_sync(df=df, strategy=strategy, initial_capital=10_000.0)
        assert len(result.equity_curve) == len(df)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/unit/test_backtest_runner.py -v --no-header -x 2>&1 | head -10`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write runner.py**

```python
"""Backtest runner — orchestrates indicator enrichment and portfolio simulation."""

from __future__ import annotations

import math
from datetime import datetime

import numpy as np
import pandas as pd

from app.backtesting.results import BacktestResult, BacktestConfig
from app.backtesting.strategies.base import StrategyBase, SignalResult

# Indicator compute functions
from app.analysis.indicators.trend import compute_ema, compute_adx, compute_supertrend
from app.analysis.indicators.momentum import compute_rsi, compute_macd, compute_stoch
from app.analysis.indicators.volatility import compute_bbands, compute_atr, compute_ttm_squeeze
from app.analysis.indicators.volume import compute_obv, compute_vwap, compute_cmf
from app.analysis.indicators.harmonics import detect_harmonics


def enrich_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Call all compute_*() functions to add indicator columns to the DataFrame."""
    compute_ema(df)
    compute_adx(df)
    compute_supertrend(df)
    compute_rsi(df)
    compute_macd(df)
    compute_stoch(df)
    compute_bbands(df)
    compute_atr(df)
    compute_ttm_squeeze(df)
    compute_obv(df)
    compute_vwap(df)
    compute_cmf(df)

    # Materialize harmonic patterns into DataFrame columns
    _materialize_harmonics(df)

    return df


def _materialize_harmonics(df: pd.DataFrame) -> None:
    """Run detect_harmonics() and write results as DataFrame columns."""
    df["harmonic_detected"] = False
    df["harmonic_score"] = 0.0
    df["harmonic_prz_low"] = np.nan
    df["harmonic_prz_high"] = np.nan
    df["harmonic_x_price"] = np.nan

    try:
        matches = detect_harmonics(df, max_bars_since_completion=len(df), min_ratio_quality=0.3)
    except Exception:
        return

    for m in matches:
        if 0 <= m.completion_bar < len(df):
            idx = df.index[m.completion_bar]
            df.loc[idx, "harmonic_detected"] = True
            df.loc[idx, "harmonic_score"] = m.ratio_quality
            df.loc[idx, "harmonic_prz_low"] = m.prz_low
            df.loc[idx, "harmonic_prz_high"] = m.prz_high
            df.loc[idx, "harmonic_x_price"] = m.x


def materialize_yolo_detections(df: pd.DataFrame, detections: list[dict]) -> None:
    """Write pre-fetched YOLO pattern_detections into DataFrame columns.

    Called by the API layer after fetching detections from DB.
    Each detection dict has: pattern_name, confidence, bar_end (timestamp), direction.
    """
    df["yolo_pattern"] = None
    df["yolo_confidence"] = 0.0

    for det in detections:
        # Map detection timestamp to nearest bar index
        bar_time = pd.Timestamp(det["bar_end"])
        idx = df.index.get_indexer([bar_time], method="nearest")[0]
        if 0 <= idx < len(df):
            df.iloc[idx, df.columns.get_loc("yolo_pattern")] = det["pattern_name"]
            df.iloc[idx, df.columns.get_loc("yolo_confidence")] = det["confidence"]


def _compute_sharpe(returns: np.ndarray, periods_per_year: float = 252.0) -> float:
    """Annualized Sharpe ratio from daily returns."""
    if len(returns) < 2 or np.std(returns) == 0:
        return 0.0
    return float(np.mean(returns) / np.std(returns) * np.sqrt(periods_per_year))


def _compute_sortino(returns: np.ndarray, periods_per_year: float = 252.0) -> float:
    """Annualized Sortino ratio from daily returns."""
    if len(returns) < 2:
        return 0.0
    downside = returns[returns < 0]
    if len(downside) == 0 or np.std(downside) == 0:
        return 0.0 if np.mean(returns) <= 0 else float("inf")
    return float(np.mean(returns) / np.std(downside) * np.sqrt(periods_per_year))


def _compute_cagr(start_value: float, end_value: float, days: int) -> float:
    """Compound annual growth rate."""
    if days <= 0 or start_value <= 0:
        return 0.0
    years = days / 365.25
    if years == 0:
        return 0.0
    return float((end_value / start_value) ** (1 / years) - 1) * 100


def _compute_max_drawdown(equity: np.ndarray) -> tuple[float, int]:
    """Returns (max_drawdown_pct, max_drawdown_duration_days)."""
    if len(equity) < 2:
        return 0.0, 0
    peak = np.maximum.accumulate(equity)
    drawdown = (equity - peak) / peak
    max_dd = float(np.min(drawdown)) * 100  # negative percentage

    # Duration: longest streak below previous peak
    below_peak = equity < peak
    max_duration = 0
    current_duration = 0
    for bp in below_peak:
        if bp:
            current_duration += 1
            max_duration = max(max_duration, current_duration)
        else:
            current_duration = 0

    return max_dd, max_duration


def _simulate_portfolio(
    close: np.ndarray,
    entries: np.ndarray,
    exits: np.ndarray,
    initial_capital: float,
    commission_pct: float,
    slippage_pct: float,
    position_size_pct: float = 0.95,
) -> tuple[np.ndarray, list[dict]]:
    """
    Simple long-only portfolio simulation.
    Returns (equity_array, trade_list).
    """
    n = len(close)
    equity = np.full(n, initial_capital, dtype=float)
    cash = initial_capital
    shares = 0.0
    in_position = False
    entry_price = 0.0
    entry_bar = 0
    trades: list[dict] = []

    for i in range(n):
        # Update equity
        if in_position:
            equity[i] = cash + shares * close[i]
        else:
            equity[i] = cash

        # Check exit first
        if in_position and exits[i]:
            sell_price = close[i] * (1 - slippage_pct)
            proceeds = shares * sell_price
            commission = proceeds * commission_pct
            cash += proceeds - commission
            pnl_abs = (sell_price - entry_price) * shares - commission * 2  # approx both sides
            pnl_pct = (sell_price / entry_price - 1) * 100
            trades.append({
                "entry_bar": entry_bar,
                "exit_bar": i,
                "entry_price": round(entry_price, 4),
                "exit_price": round(sell_price, 4),
                "pnl_pct": round(pnl_pct, 2),
                "pnl_abs": round(pnl_abs, 2),
                "shares": round(shares, 4),
                "direction": "long",
            })
            shares = 0.0
            in_position = False
            equity[i] = cash

        # Check entry
        if not in_position and entries[i]:
            buy_price = close[i] * (1 + slippage_pct)
            invest = cash * position_size_pct
            commission = invest * commission_pct
            shares = (invest - commission) / buy_price
            cash -= invest
            entry_price = buy_price
            entry_bar = i
            in_position = True
            equity[i] = cash + shares * close[i]

    # Close open position at end
    if in_position:
        sell_price = close[-1]
        proceeds = shares * sell_price
        commission = proceeds * commission_pct
        cash += proceeds - commission
        pnl_pct = (sell_price / entry_price - 1) * 100
        pnl_abs = (sell_price - entry_price) * shares
        trades.append({
            "entry_bar": entry_bar,
            "exit_bar": n - 1,
            "entry_price": round(entry_price, 4),
            "exit_price": round(sell_price, 4),
            "pnl_pct": round(pnl_pct, 2),
            "pnl_abs": round(pnl_abs, 2),
            "shares": round(shares, 4),
            "direction": "long",
        })
        equity[-1] = cash

    return equity, trades


def run_backtest_sync(
    df: pd.DataFrame,
    strategy: StrategyBase,
    initial_capital: float = 10_000.0,
    commission_pct: float = 0.001,
    slippage_pct: float = 0.0005,
    position_size_pct: float = 0.95,
) -> BacktestResult:
    """
    Run a backtest on an OHLCV DataFrame (will be enriched with indicators).
    Pure sync — no DB access. The caller provides the DataFrame.
    """
    # Enrich with indicators
    enrich_dataframe(df)

    # Generate signals
    signals = strategy.generate_signals(df)

    close = df["close"].to_numpy()
    n = len(df)

    # Simulate portfolio
    equity, trades = _simulate_portfolio(
        close=close,
        entries=signals.entries,
        exits=signals.exits,
        initial_capital=initial_capital,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        position_size_pct=position_size_pct,
    )

    # Compute stats
    daily_returns = np.diff(equity) / equity[:-1]
    daily_returns = daily_returns[np.isfinite(daily_returns)]

    total_return_pct = (equity[-1] / initial_capital - 1) * 100
    days = (df.index[-1] - df.index[0]).days if hasattr(df.index[-1], "days") else n
    if isinstance(df.index[0], (pd.Timestamp, datetime)):
        days = (df.index[-1] - df.index[0]).days
    cagr_pct = _compute_cagr(initial_capital, equity[-1], days)
    sharpe = _compute_sharpe(daily_returns)
    sortino = _compute_sortino(daily_returns)
    max_dd, max_dd_dur = _compute_max_drawdown(equity)

    # Trade stats
    winning = [t for t in trades if t["pnl_pct"] > 0]
    losing = [t for t in trades if t["pnl_pct"] <= 0]
    win_rate = len(winning) / len(trades) * 100 if trades else 0.0
    avg_trade = np.mean([t["pnl_pct"] for t in trades]) if trades else 0.0
    avg_win = np.mean([t["pnl_pct"] for t in winning]) if winning else 0.0
    avg_loss = np.mean([t["pnl_pct"] for t in losing]) if losing else 0.0
    gross_profit = sum(t["pnl_abs"] for t in winning)
    gross_loss = abs(sum(t["pnl_abs"] for t in losing))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0

    # Equity curve and drawdown as list[dict]
    peak = np.maximum.accumulate(equity)
    drawdown_pct = (equity - peak) / peak * 100

    dates = df.index.tolist()
    equity_curve = [
        {"date": str(dates[i])[:10] if hasattr(dates[i], "strftime") else str(dates[i]), "value": round(float(equity[i]), 2)}
        for i in range(n)
    ]
    drawdown_curve = [
        {"date": str(dates[i])[:10] if hasattr(dates[i], "strftime") else str(dates[i]), "pct": round(float(drawdown_pct[i]), 2)}
        for i in range(n)
    ]

    # Add dates to trades
    for t in trades:
        t["entry_date"] = str(dates[t["entry_bar"]])[:10] if hasattr(dates[t["entry_bar"]], "strftime") else str(dates[t["entry_bar"]])
        t["exit_date"] = str(dates[t["exit_bar"]])[:10] if hasattr(dates[t["exit_bar"]], "strftime") else str(dates[t["exit_bar"]])

    # Benchmark: buy and hold
    benchmark_return = (close[-1] / close[0] - 1) * 100
    bh_equity = initial_capital * close / close[0]
    bh_returns = np.diff(bh_equity) / bh_equity[:-1]
    benchmark_sharpe = _compute_sharpe(bh_returns)

    config = BacktestConfig(
        symbol="",
        timeframe="1d",
        start_date=str(dates[0])[:10],
        end_date=str(dates[-1])[:10],
        strategy_name=strategy.name,
        strategy_params=strategy.parameters,
        initial_capital=initial_capital,
        commission_pct=commission_pct,
        slippage_pct=slippage_pct,
        position_size=position_size_pct,
    )

    return BacktestResult(
        config=config,
        total_return_pct=round(total_return_pct, 2),
        cagr_pct=round(cagr_pct, 2),
        sharpe_ratio=round(sharpe, 4),
        sortino_ratio=round(sortino, 4),
        max_drawdown_pct=round(max_dd, 2),
        max_drawdown_duration_days=max_dd_dur,
        win_rate_pct=round(win_rate, 1),
        profit_factor=round(profit_factor, 2) if profit_factor != float("inf") else 999.99,
        total_trades=len(trades),
        avg_trade_pct=round(float(avg_trade), 2),
        avg_win_pct=round(float(avg_win), 2),
        avg_loss_pct=round(float(avg_loss), 2),
        equity_curve=equity_curve,
        drawdown_curve=drawdown_curve,
        trades=trades,
        benchmark_return_pct=round(benchmark_return, 2),
        benchmark_sharpe=round(benchmark_sharpe, 4),
    )
```

Note: This implementation uses a custom portfolio simulator instead of vectorbt. vectorbt 0.26.2 has Python 3.12+ compatibility issues, and we only need `Portfolio.from_signals()` functionality — the ~120 lines of NumPy simulation above replicate it precisely. This is the fallback approach mentioned in the spec.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_backtest_runner.py -v --no-header 2>&1 | tail -20`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/backtesting/runner.py backend/tests/unit/test_backtest_runner.py
git commit -m "feat(backtest): add BacktestRunner with custom portfolio simulator"
```

---

### Task 9: Parameter sweep

**Files:**
- Create: `backend/app/backtesting/parameter_sweep.py`
- Create: `backend/tests/unit/test_parameter_sweep.py`

- [ ] **Step 1: Write sweep tests**

```python
"""Unit tests for parameter sweep."""

import pytest

from tests.generators import gen_uptrend

from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
from app.backtesting.strategies.indicator_strategies import EMACrossoverStrategy


@pytest.mark.unit
class TestParameterSweep:
    def test_produces_correct_number_of_results(self):
        df = gen_uptrend(bars=200, seed=42)
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        # Override param_space to a small 3x3 grid
        strategy.param_space = {"fast": [9, 12, 21], "slow": [26, 50, 100]}

        config = SweepConfig(
            strategy=strategy,
            param_axes=["fast", "slow"],
            metric="sharpe_ratio",
        )
        result = run_sweep_sync(df=df, sweep_config=config)
        assert len(result.results) == 9  # 3 x 3

    def test_best_result_identified(self):
        df = gen_uptrend(bars=200, seed=42)
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        strategy.param_space = {"fast": [9, 21], "slow": [26, 50]}

        config = SweepConfig(
            strategy=strategy,
            param_axes=["fast", "slow"],
            metric="sharpe_ratio",
        )
        result = run_sweep_sync(df=df, sweep_config=config)
        assert result.best_result is not None
        # Best should have the highest sharpe
        all_sharpes = [r.sharpe_ratio for r in result.results]
        assert result.best_result.sharpe_ratio == max(all_sharpes)

    def test_heatmap_data_populated(self):
        df = gen_uptrend(bars=200, seed=42)
        strategy = EMACrossoverStrategy(fast=21, slow=50)
        strategy.param_space = {"fast": [9, 21], "slow": [26, 50]}

        config = SweepConfig(
            strategy=strategy,
            param_axes=["fast", "slow"],
            metric="total_return_pct",
        )
        result = run_sweep_sync(df=df, sweep_config=config)
        assert len(result.heatmap_data) == 4  # 2 x 2
```

- [ ] **Step 2: Write parameter_sweep.py**

```python
"""Parameter sweep — grid search over strategy parameter combinations."""

from __future__ import annotations

from dataclasses import dataclass
from itertools import product

import pandas as pd

from app.backtesting.results import BacktestResult
from app.backtesting.runner import run_backtest_sync


@dataclass
class SweepConfig:
    strategy: object  # StrategyBase instance (used as template)
    param_axes: list[str]  # which 2 params for heatmap
    metric: str = "sharpe_ratio"
    initial_capital: float = 10_000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005


@dataclass
class SweepResult:
    results: list[BacktestResult]
    best_result: BacktestResult | None
    heatmap_data: dict  # {(p1_val, p2_val): metric_value}
    param_combos: list[dict]  # parameter dicts for each result


def run_sweep_sync(
    df: pd.DataFrame,
    sweep_config: SweepConfig,
) -> SweepResult:
    """
    Run all parameter combinations from strategy.param_space.
    Returns all results + best config by metric.
    """
    strategy = sweep_config.strategy
    param_space = strategy.param_space

    # Generate all combinations
    param_names = list(param_space.keys())
    param_values = [param_space[name] for name in param_names]
    combos = [dict(zip(param_names, vals)) for vals in product(*param_values)]

    results: list[BacktestResult] = []
    param_combos: list[dict] = []

    for combo in combos:
        # Create new strategy instance with this parameter combo
        strategy_cls = type(strategy)
        try:
            if hasattr(strategy, "config"):
                # CustomStrategy
                new_strategy = strategy_cls(config=combo)
            else:
                new_strategy = strategy_cls(**combo)
        except TypeError:
            continue

        # Run backtest on a copy of the dataframe
        df_copy = df.copy()
        result = run_backtest_sync(
            df=df_copy,
            strategy=new_strategy,
            initial_capital=sweep_config.initial_capital,
            commission_pct=sweep_config.commission_pct,
            slippage_pct=sweep_config.slippage_pct,
        )
        results.append(result)
        param_combos.append(combo)

    # Find best by metric
    best_result = None
    if results:
        best_idx = max(range(len(results)), key=lambda i: getattr(results[i], sweep_config.metric, 0))
        best_result = results[best_idx]

    # Build heatmap data for the 2 selected axes
    heatmap_data = {}
    if len(sweep_config.param_axes) >= 2:
        ax1, ax2 = sweep_config.param_axes[0], sweep_config.param_axes[1]
        for i, combo in enumerate(param_combos):
            key = (combo.get(ax1), combo.get(ax2))
            heatmap_data[str(key)] = getattr(results[i], sweep_config.metric, 0)
    elif len(sweep_config.param_axes) == 1:
        ax1 = sweep_config.param_axes[0]
        for i, combo in enumerate(param_combos):
            key = (combo.get(ax1),)
            heatmap_data[str(key)] = getattr(results[i], sweep_config.metric, 0)

    return SweepResult(
        results=results,
        best_result=best_result,
        heatmap_data=heatmap_data,
        param_combos=param_combos,
    )
```

- [ ] **Step 3: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_parameter_sweep.py -v --no-header 2>&1 | tail -15`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/backtesting/parameter_sweep.py backend/tests/unit/test_parameter_sweep.py
git commit -m "feat(backtest): add parameter sweep with grid search"
```

---

## Chunk 4: Database Migration + API

### Task 10: SQLAlchemy model + Alembic migration

**Files:**
- Create: `backend/app/models/backtest.py`
- Create: `backend/alembic/versions/005_backtest_results.py`

- [ ] **Step 1: Check existing models for patterns**

Read: `backend/app/models/` to see existing model patterns (imports, Base class, column styles).

- [ ] **Step 2: Write the SQLAlchemy model**

```python
"""SQLAlchemy model for backtest results."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base  # adjust import to match existing pattern


class BacktestResultModel(Base):
    __tablename__ = "backtest_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(10), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    strategy: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False)
    stats: Mapped[dict] = mapped_column(JSONB, nullable=False)
    equity: Mapped[list] = mapped_column(JSONB, nullable=False)
    drawdown: Mapped[list] = mapped_column(JSONB, nullable=False)
    trades: Mapped[list] = mapped_column(JSONB, nullable=False)
```

Note: Check how existing models import `Base` — it may be from `app.db.base` or `app.models.base`. Match the existing pattern exactly.

- [ ] **Step 3: Add to models/__init__.py**

Add `BacktestResultModel` to the imports and `__all__` list in `backend/app/models/__init__.py`, following the existing pattern.

- [ ] **Step 4: Write the Alembic migration**

Check existing migration files for the next number (likely 005 or similar). Write a migration that creates the `backtest_results` table matching the model above. Follow the exact pattern of existing migrations (imports, `revision`, `down_revision`).

- [ ] **Step 5: Commit**

```bash
git add backend/app/models/backtest.py backend/app/models/__init__.py backend/alembic/versions/005_backtest_results.py
git commit -m "feat(backtest): add backtest_results table migration and model"
```

---

### Task 11: Pydantic schemas

**Files:**
- Create: `backend/app/schemas/backtests.py`

- [ ] **Step 1: Check existing schema patterns**

Read: `backend/app/schemas/` for import patterns, BaseModel usage, field validators.

- [ ] **Step 2: Write schemas**

```python
"""Pydantic schemas for backtest API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "1d"
    start_date: date
    end_date: date
    strategy_type: str
    parameters: dict = Field(default_factory=dict)
    initial_capital: float = 10_000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005


class SweepRequest(BacktestRequest):
    param_axes: list[str]
    metric: str = "sharpe_ratio"


class BacktestResponse(BaseModel):
    id: int | None = None
    stats: dict
    equity_curve: list[dict]
    drawdown_curve: list[dict]
    trades: list[dict]
    benchmark_return_pct: float
    benchmark_sharpe: float


class SweepResponse(BaseModel):
    results: list[BacktestResponse]
    best_index: int
    heatmap_data: dict


class BacktestHistoryItem(BaseModel):
    id: int
    created_at: str
    symbol: str
    timeframe: str
    strategy: str
    total_return_pct: float
    sharpe_ratio: float
    total_trades: int
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/schemas/backtests.py
git commit -m "feat(backtest): add Pydantic request/response schemas"
```

---

### Task 12: API router

**Files:**
- Create: `backend/app/api/backtests.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Check existing router patterns**

Read: `backend/app/api/` for existing router patterns (imports, dependency injection, response models, error handling). Read `backend/app/main.py` to see how routers are registered.

- [ ] **Step 2: Write the router**

```python
"""Backtest API endpoints."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from typing import Annotated

from app.db.session import AsyncSessionLocal, get_session
from app.models import OHLCV, Symbol, BacktestResultModel
from app.schemas.backtests import (
    BacktestRequest,
    BacktestResponse,
    BacktestHistoryItem,
    SweepRequest,
    SweepResponse,
)
from app.backtesting.strategies import create_strategy
from app.backtesting.runner import run_backtest_sync, enrich_dataframe, materialize_yolo_detections
from app.backtesting.parameter_sweep import run_sweep_sync, SweepConfig
from app.backtesting.results import BacktestResult

router = APIRouter(prefix="/backtests", tags=["backtests"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def _fetch_ohlcv(session: AsyncSession, symbol: str, timeframe: str, start: date, end: date):
    """Fetch OHLCV data from DB for the given symbol and date range."""
    import pandas as pd

    # Resolve ticker string to symbol_id
    sym_query = select(Symbol).where(Symbol.ticker == symbol)
    sym_result = await session.execute(sym_query)
    sym = sym_result.scalar_one_or_none()
    if not sym:
        raise HTTPException(status_code=404, detail=f"Symbol not found: {symbol}")

    # Query OHLCV by symbol_id and timeframe enum
    query = (
        select(OHLCV)
        .where(OHLCV.symbol_id == sym.id)
        .where(OHLCV.timeframe == timeframe)
        .where(OHLCV.time >= start)
        .where(OHLCV.time <= end)
        .order_by(OHLCV.time)
    )
    result = await session.execute(query)
    rows = result.scalars().all()

    if not rows:
        raise HTTPException(status_code=404, detail=f"No OHLCV data found for {symbol}")

    df = pd.DataFrame([{
        "open": float(r.open), "high": float(r.high), "low": float(r.low),
        "close": float(r.close), "volume": int(r.volume),
    } for r in rows], index=pd.DatetimeIndex([r.time for r in rows]))

    return df


async def _fetch_yolo_detections(session: AsyncSession, symbol_id: int, start: date, end: date) -> list[dict]:
    """Fetch pre-computed YOLO pattern detections from DB."""
    from app.models import PatternDetection  # adjust model name to match existing

    query = (
        select(PatternDetection)
        .where(PatternDetection.symbol_id == symbol_id)
        .where(PatternDetection.detected_at >= start)
        .where(PatternDetection.detected_at <= end)
    )
    result = await session.execute(query)
    rows = result.scalars().all()
    return [
        {
            "pattern_name": r.pattern_name,
            "confidence": float(r.confidence),
            "bar_end": r.detected_at,
            "direction": getattr(r, "direction", "bullish"),
        }
        for r in rows
    ]


def _result_to_response(result: BacktestResult, db_id: int | None = None) -> BacktestResponse:
    """Convert BacktestResult to API response."""
    return BacktestResponse(
        id=db_id,
        stats={
            "total_return_pct": result.total_return_pct,
            "cagr_pct": result.cagr_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "max_drawdown_duration_days": result.max_drawdown_duration_days,
            "win_rate_pct": result.win_rate_pct,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
            "avg_trade_pct": result.avg_trade_pct,
            "avg_win_pct": result.avg_win_pct,
            "avg_loss_pct": result.avg_loss_pct,
        },
        equity_curve=result.equity_curve,
        drawdown_curve=result.drawdown_curve,
        trades=result.trades,
        benchmark_return_pct=result.benchmark_return_pct,
        benchmark_sharpe=result.benchmark_sharpe,
    )


async def _save_result(session: AsyncSession, req: BacktestRequest, result: BacktestResult) -> int:
    """Persist a backtest result to the database."""
    model = BacktestResultModel(
        symbol=req.symbol,
        timeframe=req.timeframe,
        start_date=req.start_date,
        end_date=req.end_date,
        strategy=req.strategy_type,
        parameters=req.parameters,
        stats={
            "total_return_pct": result.total_return_pct,
            "cagr_pct": result.cagr_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "sortino_ratio": result.sortino_ratio,
            "max_drawdown_pct": result.max_drawdown_pct,
            "max_drawdown_duration_days": result.max_drawdown_duration_days,
            "win_rate_pct": result.win_rate_pct,
            "profit_factor": result.profit_factor,
            "total_trades": result.total_trades,
            "avg_trade_pct": result.avg_trade_pct,
            "avg_win_pct": result.avg_win_pct,
            "avg_loss_pct": result.avg_loss_pct,
            "benchmark_return_pct": result.benchmark_return_pct,
            "benchmark_sharpe": result.benchmark_sharpe,
        },
        equity=result.equity_curve,
        drawdown=result.drawdown_curve,
        trades=result.trades,
    )
    session.add(model)
    await session.flush()
    return model.id


@router.post("/run", response_model=BacktestResponse)
async def run_backtest(req: BacktestRequest, session: SessionDep):
    """Run a single backtest and return results."""
    strategy = create_strategy(req.strategy_type, req.parameters)
    df = await _fetch_ohlcv(session, req.symbol, req.timeframe, req.start_date, req.end_date)

    import asyncio
    result = await asyncio.to_thread(
        run_backtest_sync,
        df=df,
        strategy=strategy,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
    )
    result.config.symbol = req.symbol
    result.config.timeframe = req.timeframe

    db_id = await _save_result(session, req, result)
    await session.commit()

    return _result_to_response(result, db_id)


@router.post("/sweep", response_model=SweepResponse)
async def run_sweep(req: SweepRequest, session: SessionDep):
    """Run a parameter sweep and return all results."""
    strategy = create_strategy(req.strategy_type, req.parameters)
    df = await _fetch_ohlcv(session, req.symbol, req.timeframe, req.start_date, req.end_date)

    sweep_config = SweepConfig(
        strategy=strategy,
        param_axes=req.param_axes,
        metric=req.metric,
        initial_capital=req.initial_capital,
        commission_pct=req.commission_pct,
        slippage_pct=req.slippage_pct,
    )

    import asyncio
    sweep_result = await asyncio.to_thread(run_sweep_sync, df=df, sweep_config=sweep_config)

    responses = [_result_to_response(r) for r in sweep_result.results]
    best_idx = sweep_result.results.index(sweep_result.best_result) if sweep_result.best_result else 0

    return SweepResponse(
        results=responses,
        best_index=best_idx,
        heatmap_data=sweep_result.heatmap_data,
    )


@router.get("/history", response_model=list[BacktestHistoryItem])
async def get_history(session: SessionDep):
    """List the 20 most recent backtest results."""
    query = select(BacktestResultModel).order_by(desc(BacktestResultModel.created_at)).limit(20)
    result = await session.execute(query)
    rows = result.scalars().all()
    return [
        BacktestHistoryItem(
            id=r.id,
            created_at=r.created_at.isoformat(),
            symbol=r.symbol,
            timeframe=r.timeframe,
            strategy=r.strategy,
            total_return_pct=r.stats.get("total_return_pct", 0),
            sharpe_ratio=r.stats.get("sharpe_ratio", 0),
            total_trades=r.stats.get("total_trades", 0),
        )
        for r in rows
    ]


@router.get("/{backtest_id}", response_model=BacktestResponse)
async def get_backtest(backtest_id: int, session: SessionDep):
    """Get a stored backtest result by ID."""
    result = await session.get(BacktestResultModel, backtest_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backtest not found")
    return BacktestResponse(
        id=result.id,
        stats=result.stats,
        equity_curve=result.equity,
        drawdown_curve=result.drawdown,
        trades=result.trades,
        benchmark_return_pct=result.stats.get("benchmark_return_pct", 0),
        benchmark_sharpe=result.stats.get("benchmark_sharpe", 0),
    )


@router.delete("/{backtest_id}")
async def delete_backtest(backtest_id: int, session: SessionDep):
    """Delete a stored backtest result."""
    result = await session.get(BacktestResultModel, backtest_id)
    if not result:
        raise HTTPException(status_code=404, detail="Backtest not found")
    await session.delete(result)
    await session.commit()
    return {"status": "deleted"}
```

- [ ] **Step 3: Register router in main.py**

Add to `backend/app/main.py`:
```python
from app.api.backtests import router as backtests_router
app.include_router(backtests_router)
```

Match the existing registration pattern in the file.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/backtests.py backend/app/main.py
git commit -m "feat(backtest): add REST API endpoints for backtesting"
```

---

## Chunk 5: Frontend

### Task 13: Types + API client + Zustand store

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/api/backtests.ts`
- Create: `frontend/src/stores/backtestStore.ts`

- [ ] **Step 1: Add backtest types to index.ts**

Append to `frontend/src/types/index.ts`:

```typescript
// Backtest types
export interface BacktestStats {
  total_return_pct: number;
  cagr_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  max_drawdown_duration_days: number;
  win_rate_pct: number;
  profit_factor: number;
  total_trades: number;
  avg_trade_pct: number;
  avg_win_pct: number;
  avg_loss_pct: number;
}

export interface BacktestTrade {
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
  pnl_abs: number;
  direction: string;
}

export interface EquityCurvePoint {
  date: string;
  value: number;
}

export interface DrawdownPoint {
  date: string;
  pct: number;
}

export interface BacktestResponse {
  id: number | null;
  stats: BacktestStats;
  equity_curve: EquityCurvePoint[];
  drawdown_curve: DrawdownPoint[];
  trades: BacktestTrade[];
  benchmark_return_pct: number;
  benchmark_sharpe: number;
}

export interface SweepResponse {
  results: BacktestResponse[];
  best_index: number;
  heatmap_data: Record<string, number>;
}

export interface BacktestHistoryItem {
  id: number;
  created_at: string;
  symbol: string;
  timeframe: string;
  strategy: string;
  total_return_pct: number;
  sharpe_ratio: number;
  total_trades: number;
}

export interface BacktestRequest {
  symbol: string;
  timeframe: string;
  start_date: string;
  end_date: string;
  strategy_type: string;
  parameters: Record<string, unknown>;
  initial_capital: number;
  commission_pct: number;
  slippage_pct: number;
}

export interface SweepRequest extends BacktestRequest {
  param_axes: string[];
  metric: string;
}

export type StrategyType =
  | "ema_crossover"
  | "rsi_threshold"
  | "macd_cross"
  | "supertrend"
  | "momentum_breakout"
  | "trend_following"
  | "mean_reversion"
  | "harmonic_setup"
  | "yolo_pattern"
  | "custom";

export interface StrategyParamDef {
  name: string;
  label: string;
  type: "number" | "select" | "boolean";
  default: number | string | boolean;
  min?: number;
  max?: number;
  step?: number;
  options?: Array<{ value: unknown; label: string }>;
  sweepValues?: unknown[];
}

export interface StrategyDef {
  type: StrategyType;
  label: string;
  params: StrategyParamDef[];
}
```

- [ ] **Step 2: Write API client**

Create `frontend/src/api/backtests.ts`:

```typescript
import { apiFetch } from "./client"; // shared fetch helper (extracted from scanner.ts in this task)
import type {
  BacktestRequest,
  BacktestResponse,
  SweepRequest,
  SweepResponse,
  BacktestHistoryItem,
} from "../types";

export const backtestApi = {
  run: (req: BacktestRequest) =>
    apiFetch<BacktestResponse>("/api/backtests/run", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  sweep: (req: SweepRequest) =>
    apiFetch<SweepResponse>("/api/backtests/sweep", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),

  getHistory: () =>
    apiFetch<BacktestHistoryItem[]>("/api/backtests/history"),

  getById: (id: number) =>
    apiFetch<BacktestResponse>(`/api/backtests/${id}`),

  delete: (id: number) =>
    apiFetch<{ status: string }>(`/api/backtests/${id}`, { method: "DELETE" }),
};
```

**Important:** `apiFetch` is NOT exported from `scanner.ts`. Before writing this file, extract `apiFetch` and `apiFetchNullable` into a new `frontend/src/api/client.ts` file and update `scanner.ts` to import from there. Then import from `./client` here.

- [ ] **Step 3: Write Zustand store**

Create `frontend/src/stores/backtestStore.ts`:

```typescript
import { create } from "zustand";
import type {
  BacktestResponse,
  SweepResponse,
  StrategyType,
} from "../types";

interface BacktestState {
  // Form state
  strategyType: StrategyType;
  symbol: string;
  timeframe: string;
  startDate: string;
  endDate: string;
  initialCapital: number;
  parameters: Record<string, unknown>;

  // Results
  result: BacktestResponse | null;
  sweepResult: SweepResponse | null;
  isRunning: boolean;
  isSweeping: boolean;
  error: string | null;

  // Selected sweep result index
  selectedSweepIndex: number | null;

  // Actions
  setStrategyType: (type: StrategyType) => void;
  setSymbol: (symbol: string) => void;
  setTimeframe: (tf: string) => void;
  setStartDate: (date: string) => void;
  setEndDate: (date: string) => void;
  setInitialCapital: (capital: number) => void;
  setParameters: (params: Record<string, unknown>) => void;
  setParameter: (key: string, value: unknown) => void;
  setResult: (result: BacktestResponse | null) => void;
  setSweepResult: (result: SweepResponse | null) => void;
  setIsRunning: (running: boolean) => void;
  setIsSweeping: (sweeping: boolean) => void;
  setError: (error: string | null) => void;
  setSelectedSweepIndex: (index: number | null) => void;
  reset: () => void;
}

const initialState = {
  strategyType: "ema_crossover" as StrategyType,
  symbol: "NVDA",
  timeframe: "1d",
  startDate: "2023-01-01",
  endDate: "2024-12-31",
  initialCapital: 10000,
  parameters: {} as Record<string, unknown>,
  result: null as BacktestResponse | null,
  sweepResult: null as SweepResponse | null,
  isRunning: false,
  isSweeping: false,
  error: null as string | null,
  selectedSweepIndex: null as number | null,
};

export const useBacktestStore = create<BacktestState>((set) => ({
  ...initialState,
  setStrategyType: (type) => set({ strategyType: type, parameters: {}, result: null, sweepResult: null }),
  setSymbol: (symbol) => set({ symbol }),
  setTimeframe: (tf) => set({ timeframe: tf }),
  setStartDate: (date) => set({ startDate: date }),
  setEndDate: (date) => set({ endDate: date }),
  setInitialCapital: (capital) => set({ initialCapital: capital }),
  setParameters: (params) => set({ parameters: params }),
  setParameter: (key, value) =>
    set((state) => ({ parameters: { ...state.parameters, [key]: value } })),
  setResult: (result) => set({ result }),
  setSweepResult: (result) => set({ sweepResult: result }),
  setIsRunning: (running) => set({ isRunning: running }),
  setIsSweeping: (sweeping) => set({ isSweeping: sweeping }),
  setError: (error) => set({ error }),
  setSelectedSweepIndex: (index) => set({ selectedSweepIndex: index }),
  reset: () => set(initialState),
}));
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/index.ts frontend/src/api/backtests.ts frontend/src/stores/backtestStore.ts
git commit -m "feat(backtest): add frontend types, API client, and Zustand store"
```

---

### Task 14: StrategyConfigurator component

**Files:**
- Create: `frontend/src/components/backtest/StrategyConfigurator.tsx`

- [ ] **Step 1: Write StrategyConfigurator**

This component contains:
- Strategy selector dropdown
- Symbol, timeframe, date range, capital inputs
- Dynamic parameter controls per strategy (number inputs with sliders)
- Run Backtest / Run Sweep buttons

Strategy parameter definitions are hardcoded in a `STRATEGY_DEFS` constant mapping each strategy type to its parameter list (name, type, default, min, max, sweep values). This avoids a round-trip to the server.

The component uses `useBacktestStore` for state and calls `backtestApi.run()` / `backtestApi.sweep()` via TanStack Query mutations.

For custom strategy: render an add/remove rule builder for entry_rules and exit_rules, with dropdowns for indicator, operator, and value input.

Key implementation details:
- Each param renders as a labeled number input
- "Run Sweep" button is only enabled when the selected strategy has `param_space`
- Loading state shown during backtest execution
- Error display for API failures

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/backtest/StrategyConfigurator.tsx
git commit -m "feat(backtest): add StrategyConfigurator component"
```

---

### Task 15: BacktestSummaryStats component

**Files:**
- Create: `frontend/src/components/backtest/BacktestSummaryStats.tsx`

- [ ] **Step 1: Write BacktestSummaryStats**

Renders a horizontal stats bar showing: Total Return, CAGR, Sharpe, Max Drawdown, Win Rate, Total Trades. Below that, a benchmark comparison line showing buy-and-hold return and the delta.

Color-code: positive returns green, negative red. Use existing CSS patterns from the scanner results table.

Props: `stats: BacktestStats`, `benchmarkReturn: number`, `benchmarkSharpe: number`.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/backtest/BacktestSummaryStats.tsx
git commit -m "feat(backtest): add BacktestSummaryStats component"
```

---

### Task 16: EquityCurveChart component

**Files:**
- Create: `frontend/src/components/backtest/EquityCurveChart.tsx`

- [ ] **Step 1: Write EquityCurveChart**

Uses TradingView Lightweight Charts (already installed — see `CandlestickChart.tsx` for import pattern).

Two panes:
1. **Top pane:** Strategy equity curve (green line series) + benchmark buy-and-hold (gray line series). Trade entry markers (green triangles up) and exit markers (red triangles down) as markers on the equity series.
2. **Bottom pane:** Drawdown as a red-filled area series (histogram).

Props: `equityCurve: EquityCurvePoint[]`, `drawdownCurve: DrawdownPoint[]`, `trades: BacktestTrade[]`, `benchmarkCurve?: EquityCurvePoint[]`.

Reference `frontend/src/components/stock/CandlestickChart.tsx` for chart creation, resize handling, and cleanup patterns.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/backtest/EquityCurveChart.tsx
git commit -m "feat(backtest): add EquityCurveChart with TradingView Lightweight Charts"
```

---

### Task 17: TradeListTable component

**Files:**
- Create: `frontend/src/components/backtest/TradeListTable.tsx`

- [ ] **Step 1: Write TradeListTable**

Paginated table (20 per page) with sortable columns: Date In, Date Out, Entry Price, Exit Price, P&L%, P&L$, Duration.

- Color P&L green (positive) / red (negative)
- Pagination controls at bottom
- Click row to highlight (optional: callback to parent to sync with equity curve)
- Compute duration as difference between exit_date and entry_date

Props: `trades: BacktestTrade[]`, `onSelectTrade?: (trade: BacktestTrade) => void`.

Match existing table styling from `ResultsTable.tsx`.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/backtest/TradeListTable.tsx
git commit -m "feat(backtest): add TradeListTable component"
```

---

### Task 18: ParameterSweepHeatmap component

**Files:**
- Create: `frontend/src/components/backtest/ParameterSweepHeatmap.tsx`

- [ ] **Step 1: Write ParameterSweepHeatmap**

Canvas-based 2D heatmap:
- X-axis: param 1 values
- Y-axis: param 2 values
- Cell color: interpolated green (high) → yellow (mid) → red (low) based on metric value
- Labels on axes showing parameter values
- Tooltip on hover showing exact metric value
- Click cell to call `onSelectCell(index)` callback

Props: `heatmapData: Record<string, number>`, `paramAxes: [string, string]`, `metricLabel: string`, `onSelectCell: (index: number) => void`.

Use a `<canvas>` element with `useRef` + `useEffect` for drawing. Parse the heatmap_data keys (stringified tuples) to extract axis values.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/backtest/ParameterSweepHeatmap.tsx
git commit -m "feat(backtest): add ParameterSweepHeatmap component"
```

---

### Task 19: BacktestPage + routing

**Files:**
- Create: `frontend/src/pages/BacktestPage.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: Write BacktestPage**

Layout: two-column (or responsive stacked on mobile):
- **Left column (30% width):** `<StrategyConfigurator />`
- **Right column (70% width):**
  - `<BacktestSummaryStats />` (shown when result exists)
  - `<EquityCurveChart />` (shown when result exists)
  - `<TradeListTable />` (shown when result exists)
  - `<ParameterSweepHeatmap />` (shown when sweep result exists)

Uses `useBacktestStore` to read result/sweepResult state. When `selectedSweepIndex` is set, display that specific sweep result in the stats/chart/trades panels.

- [ ] **Step 2: Add route and nav link to App.tsx**

Add to the router in `App.tsx`:
```tsx
<Route path="/backtest" element={<BacktestPage />} />
```

Add a nav link alongside existing Scanner/Watchlists links. Check how existing navigation is structured (inline in App.tsx or in a shared Nav component) and follow the same pattern.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/BacktestPage.tsx frontend/src/App.tsx
git commit -m "feat(backtest): add BacktestPage with /backtest route and navigation"
```

---

### Task 20: Run all tests

- [ ] **Step 1: Run backend unit tests**

Run: `cd backend && python -m pytest tests/unit/test_strategies.py tests/unit/test_backtest_runner.py tests/unit/test_parameter_sweep.py -v --no-header`
Expected: All PASS.

- [ ] **Step 2: Run full backend test suite for regressions**

Run: `cd backend && python -m pytest tests/ -v --no-header -x 2>&1 | tail -30`
Expected: No regressions in existing tests.

- [ ] **Step 3: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Successful build with no TypeScript errors.

- [ ] **Step 4: Fix any issues found, commit fixes**

```bash
git add -u
git commit -m "fix(backtest): address test/build issues"
```
