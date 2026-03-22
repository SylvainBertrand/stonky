# Backtesting Engine — Design Spec

**Date:** 2026-03-14
**Status:** Approved
**Milestone:** P2 — Backtesting Engine Core + UI

---

## 1. Purpose

Add a backtesting engine to Stonky that replays historical OHLCV through strategy signal generators and produces performance statistics. The engine is a **separate module** from the live scanner — it recomputes signals from raw OHLCV using the existing indicator pipeline rather than calling `run_scanner()`.

**Library:** `vectorbt==0.26.2` (free tier, PyPI) for vectorized portfolio simulation. Note: the free version is unmaintained since 2023 (author focuses on vectorbt-pro). Pinned to exact version to avoid breakage. If dependency conflicts arise with Python 3.12+ / modern pandas, fall back to a lightweight custom Portfolio class (~80 lines of NumPy) since only `Portfolio.from_signals()` is used.

---

## 2. Architecture

### 2.1 Module Structure

```
backend/app/backtesting/
  __init__.py
  strategies/
    __init__.py
    base.py                   # StrategyBase protocol + SignalResult dataclass
    profile_strategies.py     # MomentumBreakout, TrendFollowing, MeanReversion, HarmonicSetup
    indicator_strategies.py   # EMACrossover, RSIThreshold, MACDCross, Supertrend
    pattern_strategies.py     # YOLOv8 pattern-triggered entries
    custom_strategy.py        # Ad hoc rule combos from UI config
  runner.py                   # BacktestRunner: orchestrates vectorbt execution
  parameter_sweep.py          # Grid search over parameter combinations
  results.py                  # BacktestResult dataclass + stats computation
```

### 2.2 Data Flow

```
OHLCV (DB) → DataFrame → compute_*() indicators → strategy.generate_signals()
  → vbt.Portfolio.from_signals() → BacktestResult → API response / DB storage
```

Indicators are computed **once** per backtest run via `enrich_dataframe(df)` (see Section 2.4). The enriched DataFrame is passed to `generate_signals()`. Strategies read pre-computed columns rather than recomputing.

**Actual indicator column names** (from existing `compute_*()` functions):

| Module | Function | Columns Added |
|--------|----------|---------------|
| trend | `compute_ema()` | `ema_21`, `ema_50`, `ema_200` |
| trend | `compute_adx()` | `adx`, `dmp_14`, `dmn_14` |
| trend | `compute_supertrend()` | `supertrend_dir` |
| momentum | `compute_rsi()` | `rsi_14` |
| momentum | `compute_macd()` | `macd`, `macdh`, `macds` |
| momentum | `compute_stoch()` | `stoch_k`, `stoch_d` |
| volatility | `compute_bbands()` | `bbl`, `bbm`, `bbu`, `bbp` |
| volatility | `compute_atr()` | `atr` |
| volatility | `compute_ttm_squeeze()` | `squeeze_on`, `squeeze_fired`, `squeeze_momentum` |
| volume | `compute_obv()` | `obv` |
| volume | `compute_vwap()` | `session_vwap`, `anchored_vwap` |
| volume | `compute_cmf()` | `cmf` |

**Non-column indicators** (return objects, not DataFrame columns):
- `detect_harmonics(df)` → `list[HarmonicMatch]` (pattern_name, direction, completion_bar, prz_low, prz_high, ratio_quality, x, a, b, c, d)
- `compute_fibonacci_signals()` / `compute_pivot_signals()` → signal dicts only, no DataFrame columns
- `compute_rsi_divergence_signals()` / `compute_macd_divergence_signals()` → signal dicts only, no DataFrame columns

### 2.3 Key Design Decisions

- **Reuse existing indicators:** Import directly from `app.analysis.indicators.*` — no re-implementation.
- **Pure computation core:** Strategies and runner are sync. OHLCV fetch, YOLO detection fetch, and result storage are the only DB operations — performed by the runner before/after calling strategy code.
- **vectorbt for execution:** `vbt.Portfolio.from_signals()` handles equity curve, trade extraction, stats, stop-loss/take-profit mechanics.
- **No background task queue:** Backtests run synchronously in the request. Sweeps cap at ~30s for a personal tool. Can add WebSocket progress later if needed.
- **Stop/target prices are absolute:** `SignalResult.stop_prices` and `target_prices` are per-bar absolute price levels. For trailing stops, the strategy updates the stop price each bar (e.g., `close - 1.5 * atr`). vectorbt's `sl_stop` and `tp_stop` accept percentage-from-entry; the runner converts absolute prices to percentages before passing to vectorbt.

### 2.4 Enrichment Function

```python
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
    return df
```

Lives in `runner.py`. Computes all indicators unconditionally — acceptable overhead for a personal tool.

---

## 3. Strategy Interface

```python
@dataclass
class SignalResult:
    entries: np.ndarray      # bool array, True = enter long
    exits: np.ndarray        # bool array, True = exit long
    stop_prices: np.ndarray | None = None
    target_prices: np.ndarray | None = None

class StrategyBase(Protocol):
    name: str
    parameters: dict
    param_space: dict        # {param_name: [possible_values]} for sweep

    def generate_signals(self, df: pd.DataFrame) -> SignalResult: ...
    def describe(self) -> str: ...
```

All strategies receive a DataFrame with OHLCV + pre-computed indicator columns. They return boolean entry/exit arrays of the same length.

---

## 4. Strategy Implementations

### 4.1 Profile Strategies

Each scanner profile becomes a backtest strategy. Reuses indicator compute functions from `app.analysis.indicators.*`.

**MomentumBreakoutStrategy:**
- Entry: TTM Squeeze fires AND ADX > adx_min AND RSI in [rsi_min, rsi_max] AND volume > volume_multiplier x 20-bar avg
- Exit: RSI > 75 OR Supertrend flips bearish OR trailing stop (1.5 x ATR)
- Params: `{rsi_min: 50, rsi_max: 70, adx_min: 20, volume_multiplier: 1.5, squeeze_required: True}`
- Sweep: `{rsi_min: [45,50,55], rsi_max: [65,70,75], adx_min: [15,20,25], volume_multiplier: [1.2,1.5,2.0]}`

**TrendFollowingStrategy:**
- Entry: EMA 21 > 50 > 200 AND ADX > adx_min AND RSI in pullback range
- Exit: EMA 21 crosses below EMA 50 OR Supertrend flips bearish
- Params: `{adx_min: 25, ema_stack_required: True, rsi_pullback_min: 40, rsi_pullback_max: 50}`
- Sweep: `{adx_min: [20,25,30], rsi_pullback_min: [35,40,45], rsi_pullback_max: [50,55,60]}`

**MeanReversionStrategy:**
- Entry: RSI < rsi_max AND Stoch %K < stoch_k_max AND (price <= BB lower OR not require_bb_touch) AND (CMF turning positive OR not require_cmf_positive)
- Exit: RSI > 55 OR price reaches BB midline OR stop below recent swing low
- Params: `{rsi_max: 30, stoch_k_max: 20, require_bb_touch: True, require_cmf_positive: True}`
- Sweep: `{rsi_max: [25,30,35], stoch_k_max: [15,20,25]}`

**HarmonicSetupStrategy:**
- Entry: Completed harmonic pattern with ratio_quality > min_pattern_score AND (RSI divergence OR not require_rsi_divergence)
- Exit: Price reaches 61.8% extension above PRZ OR stop beyond X point
- Params: `{min_pattern_score: 0.6, require_rsi_divergence: True}`
- Sweep: `{min_pattern_score: [0.5,0.6,0.7,0.8]}`
- **Data flow:** `detect_harmonics(df)` returns `list[HarmonicMatch]`, not DataFrame columns. The runner calls `detect_harmonics()` separately and materializes results into the DataFrame as columns: `harmonic_detected` (bool), `harmonic_score` (float), `harmonic_prz_low`, `harmonic_prz_high`, `harmonic_x_price` — one row per bar, set at `completion_bar`. The strategy reads these columns like any other indicator.

### 4.2 Indicator Strategies (Baseline)

**EMACrossoverStrategy:** fast EMA crosses above/below slow EMA. Params: `{fast: 21, slow: 50}`

**RSIThresholdStrategy:** RSI crosses above oversold (entry) / above overbought (exit). Params: `{oversold: 30, overbought: 70}`

**MACDCrossStrategy:** MACD line crosses above/below signal line. Params: `{fast: 12, slow: 26, signal: 9}`

**SupertrendStrategy:** Price crosses above/below Supertrend line. Params: `{atr_period: 10, multiplier: 3.0}`

### 4.3 Pattern Strategy

**YOLOv8PatternStrategy:** Entry on bar following YOLO-detected pattern completion. Exit via ATR trailing stop or pattern height target. Params: `{pattern_names: [...], min_confidence: 0.7}`
- **Data flow:** The runner pre-fetches `pattern_detections` from DB for the symbol/date range and materializes them into the DataFrame as columns: `yolo_pattern` (str|None), `yolo_confidence` (float), `yolo_direction` (str), `yolo_bar_end` (int) — set at each detection's `bar_end` index. The strategy reads these columns; it never touches the DB directly.

### 4.4 Custom Strategy

Rule combiner configured via JSON dict from UI:
```json
{
  "entry_rules": [{"indicator": "rsi", "operator": "<", "value": 35}, ...],
  "exit_rules": [...],
  "rule_logic": "AND",
  "stop_type": "atr",
  "stop_value": 1.5,
  "target_type": "rr",
  "target_value": 2.0
}
```

Supported indicators (mapped to DataFrame columns): `rsi` → `rsi_14`, `macd_hist` → `macdh`, `adx` → `adx`, `stoch_k` → `stoch_k`, `supertrend` → `supertrend_dir`, `ema21_slope` → computed as diff of `ema_21`, `obv_slope` → computed as diff of `obv`, `cmf` → `cmf`, `bb_pct` → `bbp`, `squeeze_on` → `squeeze_on`, `squeeze_fired` → `squeeze_fired`.

Allowed operators: `<`, `>`, `<=`, `>=`, `==`, `crosses_above`, `crosses_below`. No `eval()` — operators are mapped to NumPy comparison functions via a safe dispatch dict.

---

## 5. Execution Engine

### 5.1 BacktestRunner

```python
@dataclass
class BacktestConfig:
    symbol: str
    timeframe: str              # "1d" | "1w"
    start_date: str
    end_date: str
    strategy: StrategyBase
    initial_capital: float = 10_000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005
    size_type: str = "percent"
    position_size: float = 0.95
    allow_shorting: bool = False
```

Steps:
1. Fetch OHLCV for symbol/timeframe/date range from DB
2. Compute all required indicators via existing pipeline compute functions
3. Call `strategy.generate_signals(enriched_df)`
4. Feed entries/exits + stops/targets to `vbt.Portfolio.from_signals()`
5. Extract stats, trade log, equity curve, drawdown
6. Compute benchmark (buy-and-hold same period)
7. Return `BacktestResult`

### 5.2 Parameter Sweep

Generates cartesian product from `strategy.param_space`. Runs each config as a backtest sequentially (strategies are sync CPU-bound code; concurrency adds complexity without meaningful speedup for a personal tool). Returns all results + best config by selected metric (default: Sharpe ratio).

Heatmap data: `{(param1_val, param2_val): metric_value}` for the 2 selected sweep axes.

---

## 6. Results

```python
@dataclass
class BacktestResult:
    config: BacktestConfig
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
    equity_curve: list[dict]       # [{date, value}]
    drawdown_curve: list[dict]     # [{date, pct}]
    trades: list[dict]             # [{entry_date, exit_date, entry_price, exit_price, pnl_pct, pnl_abs, direction}]
    benchmark_return_pct: float
    benchmark_sharpe: float         # computed from daily returns of buy-and-hold, not trade returns
```

---

## 7. API Endpoints

New router `backend/app/api/backtests.py`, mounted at `/api/backtests`.

### Pydantic Schemas (`backend/app/schemas/backtests.py`)

```python
class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "1d"
    start_date: date
    end_date: date
    strategy_type: str          # "momentum_breakout", "ema_crossover", "custom", etc.
    parameters: dict = {}       # strategy-specific params
    initial_capital: float = 10_000.0
    commission_pct: float = 0.001
    slippage_pct: float = 0.0005

class SweepRequest(BacktestRequest):
    param_axes: list[str]       # which 2 params for heatmap
    metric: str = "sharpe_ratio"

class BacktestResponse(BaseModel):
    id: int | None = None       # None if not yet persisted
    stats: dict                 # all scalar metrics
    equity_curve: list[dict]
    drawdown_curve: list[dict]
    trades: list[dict]
    benchmark_return_pct: float
    benchmark_sharpe: float

class SweepResponse(BaseModel):
    results: list[BacktestResponse]
    best_index: int
    heatmap_data: dict          # serialized {param_combo: metric_value}
```

| Method | Path | Description |
|--------|------|-------------|
| POST | `/run` | Run single backtest, return result |
| POST | `/sweep` | Run parameter sweep, return all results |
| GET | `/history` | List last 20 stored results |
| GET | `/{id}` | Get stored result by ID |
| DELETE | `/{id}` | Delete stored result |

### Storage

New `backtest_results` table (next available Alembic migration):

```sql
CREATE TABLE backtest_results (
    id          SERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    symbol      VARCHAR(20) NOT NULL,
    timeframe   VARCHAR(10) NOT NULL,
    start_date  DATE NOT NULL,
    end_date    DATE NOT NULL,
    strategy    VARCHAR(50) NOT NULL,
    parameters  JSONB NOT NULL,
    stats       JSONB NOT NULL,
    equity      JSONB NOT NULL,
    drawdown    JSONB NOT NULL,
    trades      JSONB NOT NULL
);
```

---

## 8. Frontend

### 8.1 Route & Navigation

New route `/backtest` → `BacktestPage.tsx`. Nav link added alongside Scanner/Watchlists.

### 8.2 Components

**StrategyConfigurator** (left panel):
- Strategy selector dropdown (all 10 strategies)
- Symbol, timeframe, date range, capital inputs
- Dynamic parameter sliders per strategy
- Custom strategy rule builder (add/remove entry/exit rules)
- Run Backtest / Run Sweep buttons

**BacktestSummaryStats:**
- Key metrics bar: total return, CAGR, Sharpe, max DD, win rate, total trades
- Benchmark comparison (buy-and-hold delta)

**EquityCurveChart:**
- TradingView Lightweight Charts (consistent with existing charts)
- Strategy equity curve (green) + benchmark overlay (gray dashed)
- Drawdown pane below (red filled area)
- Trade markers (triangle up = entry, triangle down = exit)

**TradeListTable:**
- Paginated (20 per page), sortable columns
- Color-coded P&L (green/red)
- Click row to highlight on equity curve

**ParameterSweepHeatmap:**
- Canvas/SVG-based 2D heatmap (no new charting dependency)
- X/Y axes = 2 selected sweep parameters
- Cell color = metric value (green = high, red = low)
- Click cell to load that parameter combo's full result

### 8.3 State Management

- `backtestStore` (Zustand) — selected strategy, params, results, sweep state
- TanStack Query — API calls for run/sweep/history

---

## 9. Testing

### Unit Tests (no DB, no I/O)

**test_strategies.py:**
- Each strategy generates signals of correct length (same as input DataFrame)
- Entry/exit arrays are boolean dtype
- No lookahead bias: signals at bar N only use data up to bar N
- EMACrossover: verify signals on synthetic data with known crossover points

**test_backtest_runner.py:**
- Full backtest on synthetic OHLCV returns BacktestResult with all expected fields
- Commission/slippage applied (test with 0% vs non-zero, verify difference)
- Benchmark return matches manual buy-and-hold calculation

**test_parameter_sweep.py:**
- Sweep over 3x3 param grid produces 9 results
- Best result correctly identified by metric

All tests use synthetic OHLCV data with deterministic random seeds — no yfinance or DB.

---

## 10. Dependencies

**Backend:** Add `vectorbt==0.26.2` to `pyproject.toml`

**Frontend:** No new dependencies. Heatmap built with canvas/SVG. Charts use existing `lightweight-charts`.

---

## 11. Migration Plan

Single Alembic migration (next available number) for `backtest_results` table. No changes to existing tables.

---

## 12. Out of Scope

- Walk-forward optimization
- Multi-symbol portfolio backtesting
- Short selling strategies (flag exists but not implemented)
- Real-time paper trading
- WebSocket progress for long-running sweeps
