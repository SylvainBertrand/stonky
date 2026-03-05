# Elliott Wave Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement Elliott Wave detection inline in the scanner pipeline and surface results in the frontend via a banner, chart overlay, toggle, and scanner table column.

**Architecture:** Custom hybrid greedy + Fibonacci-ratio detection runs inline in `run_analysis()` using existing swing point infrastructure. A new API endpoint re-runs detection on-demand for the frontend chart overlay. Frontend surfaces results in ElliottWaveBanner, a canvas polyline overlay, and ResultsTable column.

**Tech Stack:** Python (numpy/pandas), FastAPI, React/TypeScript, TanStack Query, HTML Canvas API

---

## Task 1: EW Detection Module — Core Types and Helpers

**Files:**
- Create: `backend/app/analysis/indicators/elliott_wave.py`
- Create: `backend/tests/unit/test_elliott_wave.py`

**Step 1: Write the failing test**

Create `backend/tests/unit/test_elliott_wave.py`:

```python
"""Unit tests for Elliott Wave detection."""
import pytest
import numpy as np
import pandas as pd
from app.analysis.indicators.elliott_wave import (
    WavePoint, WaveSequence, EWResult,
    _fib_score, _impulse_confidence, _check_impulse_rules,
    _corrective_confidence,
)


def test_fib_score_exact_match():
    assert _fib_score(0.618, 0.618) == pytest.approx(1.0)


def test_fib_score_at_tolerance_boundary():
    # At exactly tolerance away → score = 0
    score = _fib_score(0.618 * 1.25, 0.618, tolerance=0.25)
    assert score == pytest.approx(0.0, abs=0.01)


def test_fib_score_beyond_tolerance():
    assert _fib_score(0.1, 0.618) == pytest.approx(0.0)


def test_impulse_confidence_perfect_fib():
    # Perfect Fibonacci ratios for bullish: W1 up 100, W2 down 61.8, W3 up 161.8, W4 down 38.2*161.8≈61.8, W5 up 100
    p = [100.0, 200.0, 138.2, 300.0, 238.2, 338.2]
    conf = _impulse_confidence(p)
    assert conf > 0.5  # should be reasonably high


def test_impulse_confidence_terrible_ratios():
    # Completely wrong ratios → low score
    p = [100.0, 200.0, 190.0, 200.0, 195.0, 200.1]
    conf = _impulse_confidence(p)
    assert conf < 0.3


def test_check_impulse_rules_valid_bullish():
    # w0=100, w1=200, w2=138, w3=310, w4=240, w5=350
    prices = [100.0, 200.0, 138.0, 310.0, 240.0, 350.0]
    assert _check_impulse_rules(prices, 'bullish') is True


def test_check_impulse_rules_w2_below_w0():
    # W2 below W0 → invalid
    prices = [100.0, 200.0, 90.0, 310.0, 240.0, 350.0]
    assert _check_impulse_rules(prices, 'bullish') is False


def test_check_impulse_rules_w4_overlaps_w1():
    # W4 below W1 → invalid (overlap)
    prices = [100.0, 200.0, 150.0, 310.0, 180.0, 350.0]
    assert _check_impulse_rules(prices, 'bullish') is False


def test_check_impulse_rules_w3_shortest():
    # W3 is shortest → invalid
    prices = [100.0, 200.0, 160.0, 200.0, 170.0, 350.0]
    assert _check_impulse_rules(prices, 'bullish') is False


def test_check_impulse_rules_valid_bearish():
    prices = [350.0, 240.0, 310.0, 138.0, 200.0, 100.0]
    assert _check_impulse_rules(prices, 'bearish') is True


def test_check_impulse_rules_bearish_w2_above_w0():
    prices = [350.0, 240.0, 360.0, 138.0, 200.0, 100.0]
    assert _check_impulse_rules(prices, 'bearish') is False


def test_corrective_confidence_perfect_fib():
    # B retraces 61.8% of A, C = A
    p = [200.0, 100.0, 161.8, 61.8]
    conf = _corrective_confidence(p)
    assert conf > 0.5


def test_corrective_confidence_zero_amplitude():
    p = [100.0, 100.0, 90.0, 80.0]  # amp_a = 0
    assert _corrective_confidence(p) == 0.0
```

**Step 2: Run to verify it fails**

```bash
cd backend && uv run --extra dev python -m pytest tests/unit/test_elliott_wave.py -v 2>&1 | head -20
```
Expected: `ModuleNotFoundError` or `ImportError` for `elliott_wave`.

**Step 3: Create the module with the helpers**

Create `backend/app/analysis/indicators/elliott_wave.py`:

```python
"""Elliott Wave detection — hybrid greedy + Fibonacci-ratio algorithm.

Detects 5-wave impulse and 3-wave corrective (A-B-C) structures using
existing swing point infrastructure. Runs inline in the analysis pipeline.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd


# ── Data types ────────────────────────────────────────────────────────────────

@dataclass
class WavePoint:
    time: str
    price: float
    label: str      # "0","1","2","3","4","5" or "0","A","B","C"
    bar_index: int


@dataclass
class WaveSequence:
    wave_type: Literal['impulse', 'corrective']
    direction: Literal['bullish', 'bearish']
    waves: list[WavePoint]   # 6 pts for impulse, 4 for corrective
    confidence: float        # 0–1


@dataclass
class EWResult:
    best_wave: WaveSequence | None = None
    current_position: str | None = None   # "wave_3", "wave_5", "wave_A", etc.
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
        _fib_score(amp2 / amp1, 0.618),   # W2 retraces 61.8% of W1
        _fib_score(amp3 / amp1, 1.618),   # W3 = 161.8% of W1
        _fib_score(amp4 / amp3, 0.382) if amp3 > 0 else 0.0,  # W4 retraces 38.2% of W3
        _fib_score(amp5 / amp1, 1.0),     # W5 = 100% of W1
    ]
    return float(np.mean(scores))


def _check_impulse_rules(prices: list[float], direction: Literal['bullish', 'bearish']) -> bool:
    """Validate core Elliott Wave impulse rules."""
    p0, p1, p2, p3, p4, p5 = prices

    if direction == 'bullish':
        if not (p1 > p0 and p2 < p1 and p3 > p2 and p4 < p3 and p5 > p4):
            return False
        if p2 <= p0:            # W2 never below W0
            return False
        if p4 <= p1:            # W4 never below W1 (no overlap)
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
        _fib_score(amp_b / amp_a, 0.618),   # B retraces 61.8% of A
        _fib_score(amp_c / amp_a, 1.0),     # C = A
    ]
    return float(np.mean(scores))
```

**Step 4: Run tests to verify they pass**

```bash
cd backend && uv run --extra dev python -m pytest tests/unit/test_elliott_wave.py -v
```
Expected: All 12 tests PASS.

**Step 5: Commit**

```bash
cd backend && git add app/analysis/indicators/elliott_wave.py tests/unit/test_elliott_wave.py
git commit -m "feat: Elliott Wave detection helpers (fib scoring, impulse rules)"
```

---

## Task 2: EW Detection — Full `detect_elliott_waves` and Signals

**Files:**
- Modify: `backend/app/analysis/indicators/elliott_wave.py` (add detection + signals)
- Modify: `backend/tests/unit/test_elliott_wave.py` (add detection tests)

**Step 1: Write failing tests (append to test file)**

Append to `backend/tests/unit/test_elliott_wave.py`:

```python
from app.analysis.indicators.elliott_wave import (
    detect_elliott_waves, compute_ew_signals,
)
from app.analysis.swing_points import detect_swing_points
import pandas_ta as ta


def _make_impulse_df() -> tuple[pd.DataFrame, np.ndarray, np.ndarray]:
    """Synthetic bullish impulse: clear 5-wave up structure."""
    # Prices trace a textbook 5-wave: 100 → 200 → 138 → 310 → 248 → 350
    raw = [
        100, 120, 150, 180, 200,   # wave 1 up
        190, 175, 155, 138,         # wave 2 down (61.8% retrace)
        170, 200, 240, 280, 310,   # wave 3 up (161.8% of wave 1)
        295, 270, 248,              # wave 4 down (38.2% of wave 3)
        270, 300, 330, 350,        # wave 5 up (~100% of wave 1)
    ]
    df = pd.DataFrame({
        'time': pd.date_range('2024-01-01', periods=len(raw), freq='D').strftime('%Y-%m-%d'),
        'open': raw,
        'high': [p + 5 for p in raw],
        'low': [p - 5 for p in raw],
        'close': raw,
        'volume': [1_000_000] * len(raw),
    })
    atr = ta.atr(df['high'], df['low'], df['close'], length=5)
    sh, sl = detect_swing_points(df['high'], order=2, atr_filter=0.0)
    sh_idx = np.where(sh)[0]
    sl_idx = np.where(sl)[0]
    return df, sh_idx, sl_idx


def test_detect_impulse_finds_wave_sequence():
    df, sh_idx, sl_idx = _make_impulse_df()
    result = detect_elliott_waves(df, sh_idx, sl_idx)
    assert result.best_wave is not None
    assert result.best_wave.wave_type == 'impulse'
    assert result.best_wave.direction == 'bullish'
    assert len(result.best_wave.waves) == 6
    assert result.best_wave.confidence > 0.0


def test_detect_no_swings_returns_empty():
    df = pd.DataFrame({
        'time': ['2024-01-01'] * 5,
        'high': [100.0] * 5,
        'low': [99.0] * 5,
        'close': [100.0] * 5,
    })
    result = detect_elliott_waves(df, np.array([]), np.array([]))
    assert result.best_wave is None
    assert result.confidence == 0.0


def test_detect_too_few_pivots_returns_empty():
    df = pd.DataFrame({
        'time': pd.date_range('2024-01-01', periods=10, freq='D').strftime('%Y-%m-%d'),
        'high': [100.0] * 10,
        'low': [99.0] * 10,
        'close': [100.0] * 10,
    })
    result = detect_elliott_waves(df, np.array([1, 5]), np.array([3]))
    assert result.best_wave is None


def test_compute_ew_signals_with_wave3():
    """Signals include ew_wave3_active=1.0 when in wave 3."""
    # Build a mock result with wave_3 position
    from app.analysis.indicators.elliott_wave import WavePoint, WaveSequence, EWResult
    wp = [WavePoint('2024-01-01', float(p), str(i), i) for i, p in enumerate([100, 200, 138, 310, 248, 350])]
    seq = WaveSequence('impulse', 'bullish', wp, confidence=0.75)
    result = EWResult(best_wave=seq, current_position='wave_3', confidence=0.75)
    sigs = compute_ew_signals(result)
    assert sigs['ew_wave3_active'] == 1.0
    assert sigs['ew_wave5_active'] == 0.0
    assert sigs['ew_corrective_abc'] == 0.0
    assert sigs['ew_ratio_quality'] == pytest.approx(0.75)


def test_compute_ew_signals_no_wave():
    result = EWResult()
    sigs = compute_ew_signals(result)
    assert sigs['ew_wave3_active'] == 0.0
    assert sigs['ew_wave5_active'] == 0.0
    assert sigs['ew_corrective_abc'] == 0.0
    assert sigs['ew_ratio_quality'] == 0.0


def test_compute_ew_signals_corrective():
    from app.analysis.indicators.elliott_wave import WavePoint, WaveSequence, EWResult
    wp = [WavePoint('2024-01-01', float(p), lbl, i)
          for i, (p, lbl) in enumerate([(350, '0'), (200, 'A'), (280, 'B'), (180, 'C')])]
    seq = WaveSequence('corrective', 'bearish', wp, confidence=0.6)
    result = EWResult(best_wave=seq, current_position='wave_C', confidence=0.6)
    sigs = compute_ew_signals(result)
    assert sigs['ew_corrective_abc'] == pytest.approx(-0.3)
```

**Step 2: Run to verify they fail**

```bash
cd backend && uv run --extra dev python -m pytest tests/unit/test_elliott_wave.py::test_detect_impulse_finds_wave_sequence tests/unit/test_elliott_wave.py::test_compute_ew_signals_with_wave3 -v
```
Expected: `ImportError` for `detect_elliott_waves`.

**Step 3: Implement `detect_elliott_waves` and `compute_ew_signals`**

Append to `backend/app/analysis/indicators/elliott_wave.py`:

```python
from app.analysis.swing_points import detect_swing_points
import pandas_ta as ta


# ── Main detection function ────────────────────────────────────────────────────

def detect_elliott_waves(
    df: pd.DataFrame,
    swing_high_idx: np.ndarray,
    swing_low_idx: np.ndarray,
    lookback_bars: int = 120,
) -> EWResult:
    """Detect Elliott Wave patterns using pre-computed swing point indices."""
    if len(swing_high_idx) < 3 or len(swing_low_idx) < 3:
        return EWResult()

    last_bar = len(df) - 1
    start_bar = max(0, last_bar - lookback_bars)

    times = df['time'].tolist() if 'time' in df.columns else [str(i) for i in range(len(df))]
    highs_col = df['high'].to_numpy()
    lows_col = df['low'].to_numpy()

    # Build pivot list: (bar_index, price, time_str, kind)
    pivots: list[tuple[int, float, str, str]] = []
    for i in swing_high_idx:
        if i >= start_bar:
            pivots.append((int(i), float(highs_col[i]), str(times[i]), 'high'))
    for i in swing_low_idx:
        if i >= start_bar:
            pivots.append((int(i), float(lows_col[i]), str(times[i]), 'low'))
    pivots.sort(key=lambda x: x[0])

    if len(pivots) < 4:
        return EWResult()

    best: WaveSequence | None = None

    # Scan for 5-wave impulse (6 consecutive alternating pivots)
    if len(pivots) >= 6:
        for start in range(len(pivots) - 5):
            window = pivots[start:start + 6]
            prices = [pt[1] for pt in window]
            kinds = [pt[3] for pt in window]

            direction: Literal['bullish', 'bearish'] | None = None
            if kinds == ['low', 'high', 'low', 'high', 'low', 'high']:
                direction = 'bullish'
            elif kinds == ['high', 'low', 'high', 'low', 'high', 'low']:
                direction = 'bearish'

            if direction and _check_impulse_rules(prices, direction):
                conf = _impulse_confidence(prices)
                if best is None or conf > best.confidence:
                    wave_points = [
                        WavePoint(time=window[i][2], price=window[i][1],
                                  label=str(i), bar_index=window[i][0])
                        for i in range(6)
                    ]
                    best = WaveSequence('impulse', direction, wave_points, conf)

    # Scan for 3-wave corrective (4 consecutive alternating pivots)
    for start in range(len(pivots) - 3):
        window = pivots[start:start + 4]
        prices = [pt[1] for pt in window]
        kinds = [pt[3] for pt in window]

        corr_dir: Literal['bullish', 'bearish'] | None = None
        if (kinds == ['high', 'low', 'high', 'low'] and
                prices[1] < prices[0] and prices[2] > prices[1] and prices[3] < prices[2]):
            corr_dir = 'bearish'
        elif (kinds == ['low', 'high', 'low', 'high'] and
                prices[1] > prices[0] and prices[2] < prices[1] and prices[3] > prices[2]):
            corr_dir = 'bullish'

        if corr_dir is not None:
            conf = _corrective_confidence(prices) * 0.7   # discount vs impulse
            if best is None or conf > best.confidence:
                labels = ['0', 'A', 'B', 'C']
                wave_points = [
                    WavePoint(time=window[i][2], price=window[i][1],
                              label=labels[i], bar_index=window[i][0])
                    for i in range(4)
                ]
                best = WaveSequence('corrective', corr_dir, wave_points, conf)

    if best is None:
        return EWResult()

    current_pos = _determine_current_position(best, last_bar)
    return EWResult(best_wave=best, current_position=current_pos, confidence=best.confidence)


def _determine_current_position(wave: WaveSequence, last_bar: int) -> str | None:
    """Determine which wave segment the last bar falls in."""
    waves = wave.waves
    for i in range(len(waves) - 1):
        if waves[i].bar_index <= last_bar <= waves[i + 1].bar_index:
            if wave.wave_type == 'impulse':
                return f'wave_{i + 1}'
            else:
                labels = ['A', 'B', 'C']
                if i < len(labels):
                    return f'wave_{labels[i]}'
    if last_bar > waves[-1].bar_index:
        return 'wave_5_complete' if wave.wave_type == 'impulse' else 'wave_C_complete'
    return None


# ── Signal computation ─────────────────────────────────────────────────────────

def compute_ew_signals(result: EWResult) -> dict[str, float]:
    """Convert EWResult into normalized signals for the pipeline scoring."""
    signals: dict[str, float] = {'ew_ratio_quality': result.confidence}
    pos = result.current_position
    if pos is None or result.best_wave is None:
        signals['ew_wave3_active'] = 0.0
        signals['ew_wave5_active'] = 0.0
        signals['ew_corrective_abc'] = 0.0
        return signals
    signals['ew_wave3_active'] = 1.0 if pos == 'wave_3' else 0.0
    signals['ew_wave5_active'] = 0.5 if pos == 'wave_5' else 0.0
    signals['ew_corrective_abc'] = -0.3 if result.best_wave.wave_type == 'corrective' else 0.0
    return signals
```

**Step 4: Run tests**

```bash
cd backend && uv run --extra dev python -m pytest tests/unit/test_elliott_wave.py -v
```
Expected: All tests PASS. (Some detection tests may be brittle depending on synthetic data swing detection — adjust `order=` param if needed.)

**Step 5: Commit**

```bash
cd backend && git add app/analysis/indicators/elliott_wave.py tests/unit/test_elliott_wave.py
git commit -m "feat: Elliott Wave detect_elliott_waves + compute_ew_signals"
```

---

## Task 3: Pipeline Integration

**Files:**
- Modify: `backend/app/analysis/pipeline.py`
- Modify: `backend/tests/unit/test_elliott_wave.py` (add pipeline smoke test)

**Step 1: Write failing test**

Append to `backend/tests/unit/test_elliott_wave.py`:

```python
from app.analysis.pipeline import run_analysis


def _make_long_df(n: int = 250) -> pd.DataFrame:
    """Flat price DataFrame with enough bars for MIN_BARS."""
    import numpy as np
    prices = 100.0 + np.cumsum(np.random.default_rng(42).normal(0, 1, n))
    return pd.DataFrame({
        'time': pd.date_range('2020-01-01', periods=n, freq='D').strftime('%Y-%m-%d'),
        'open': prices,
        'high': prices + 1,
        'low': prices - 1,
        'close': prices,
        'volume': [1_000_000] * n,
    })


def test_pipeline_includes_ew_signals():
    """run_analysis must include ew_* signals in the output."""
    df = _make_long_df()
    result = run_analysis(df, 'TEST')
    assert 'ew_ratio_quality' in result.signals
    assert 'ew_wave3_active' in result.signals
    assert 'ew_wave5_active' in result.signals
    assert 'ew_corrective_abc' in result.signals
```

**Step 2: Run to verify it fails**

```bash
cd backend && uv run --extra dev python -m pytest tests/unit/test_elliott_wave.py::test_pipeline_includes_ew_signals -v
```
Expected: FAIL with assertion error (signals missing).

**Step 3: Integrate into `pipeline.py`**

In `backend/app/analysis/pipeline.py`:

3a. Add import at the top (after the harmonics import block, around line 30):
```python
from app.analysis.indicators.elliott_wave import (
    EWResult,
    compute_ew_signals,
    detect_elliott_waves,
)
```

3b. Add import for `detect_swing_points` (alongside other imports):
```python
from app.analysis.swing_points import detect_swing_points
```

3c. In `run_analysis()`, after the YOLO signals block (after line ~246), add:

```python
    # Elliott Wave detection — greedy scan on swing points
    try:
        import pandas_ta as ta as _ta
        atr_ser = _ta.atr(df["high"], df["low"], df["close"], length=14)
        sh_bool, sl_bool = detect_swing_points(
            df["high"],
            order=5,
            atr_filter=0.5,
            atr_series=atr_ser,
        )
        # Also use lows for swing lows
        _, sl_bool = detect_swing_points(
            df["low"],
            order=5,
            atr_filter=0.5,
            atr_series=atr_ser,
        )
        import numpy as np as _np
        sh_idx = _np.where(sh_bool)[0]
        sl_idx = _np.where(sl_bool)[0]
        ew_result = detect_elliott_waves(df, sh_idx, sl_idx)
        all_signals.update(compute_ew_signals(ew_result))
    except Exception as exc:
        log.warning("Elliott Wave analysis failed for %s: %s", symbol, exc)
```

Wait — inline imports are bad style. The existing code uses top-level imports. Fix the above: numpy and pandas_ta are already imported at the top of pipeline.py. Use the module-level imports.

Actually, re-examine. The file has `import pandas_ta as ta` at top. numpy is not directly imported but used inside indicator modules. Add `import numpy as np` at top if not already there.

Check: `grep -n "import numpy" backend/app/analysis/pipeline.py`

If missing, add `import numpy as np` to the imports. Then use:

```python
    # Elliott Wave detection — greedy scan on swing points
    try:
        atr_ser = ta.atr(df["high"], df["low"], df["close"], length=14)
        sh_bool, _ = detect_swing_points(
            df["high"], order=5, atr_filter=0.5, atr_series=atr_ser,
        )
        _, sl_bool = detect_swing_points(
            df["low"], order=5, atr_filter=0.5, atr_series=atr_ser,
        )
        sh_idx = np.where(sh_bool)[0]
        sl_idx = np.where(sl_bool)[0]
        ew_result = detect_elliott_waves(df, sh_idx, sl_idx)
        all_signals.update(compute_ew_signals(ew_result))
    except Exception as exc:
        log.warning("Elliott Wave analysis failed for %s: %s", symbol, exc)
```

**Step 4: Run tests**

```bash
cd backend && uv run --extra dev python -m pytest tests/unit/test_elliott_wave.py -v
```
Expected: All tests PASS.

Also run full unit suite to check for regressions:
```bash
cd backend && uv run --extra dev python -m pytest -m unit -v 2>&1 | tail -20
```

**Step 5: Commit**

```bash
cd backend && git add app/analysis/pipeline.py tests/unit/test_elliott_wave.py
git commit -m "feat: integrate Elliott Wave signals into analysis pipeline"
```

---

## Task 4: API Endpoint for Elliott Wave

**Files:**
- Modify: `backend/app/schemas/patterns.py`
- Modify: `backend/app/api/patterns.py`

**Step 1: Add schema to `patterns.py`**

Append to `backend/app/schemas/patterns.py`:

```python
class EWWavePointResponse(BaseModel):
    time: str
    price: float
    label: str
    bar_index: int


class EWDetectionResponse(BaseModel):
    symbol: str
    wave_type: str | None = None         # "impulse" | "corrective" | None
    direction: str | None = None         # "bullish" | "bearish" | None
    current_position: str | None = None  # "wave_3", "wave_C", etc.
    confidence: float = 0.0
    waves: list[EWWavePointResponse] = []
```

**Step 2: Add endpoint to `patterns.py`**

In `backend/app/api/patterns.py`, add the import at the top:
```python
from app.analysis.indicators.elliott_wave import detect_elliott_waves, compute_ew_signals
from app.analysis.swing_points import detect_swing_points
from app.models.ohlcv import OHLCV
from app.schemas.patterns import EWDetectionResponse, EWWavePointResponse
```

Also add to existing imports block: `import numpy as np`, `import pandas as pd`, `import pandas_ta as ta`.

Then add the new endpoint (before the existing `@router.get("/{symbol}")` if possible, or add a new prefix — but since the existing router is `prefix="/patterns"`, add a separate path):

```python
@router.get("/elliott-wave/{symbol}", response_model=EWDetectionResponse)
async def get_elliott_wave(
    symbol: str,
    session: SessionDep,
    timeframe: Annotated[str, Query(description="1d or 1w")] = "1d",
) -> EWDetectionResponse:
    """Return the latest Elliott Wave detection for a symbol."""
    tf_enum = _TF_MAP.get(timeframe, TimeframeEnum.D1)

    # Look up symbol
    sym_row = await session.execute(
        select(Symbol).where(Symbol.ticker == symbol.upper())
    )
    sym = sym_row.scalar_one_or_none()
    if sym is None:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found")

    # Fetch OHLCV
    bars_result = await session.execute(
        select(OHLCV)
        .where(OHLCV.symbol_id == sym.id, OHLCV.timeframe == tf_enum)
        .order_by(desc(OHLCV.time))
        .limit(300)
    )
    rows = bars_result.scalars().all()
    if not rows:
        return EWDetectionResponse(symbol=symbol.upper())

    rows = list(reversed(rows))
    df = pd.DataFrame([
        {"time": r.time.strftime("%Y-%m-%d"), "high": float(r.high),
         "low": float(r.low), "close": float(r.close),
         "open": float(r.open), "volume": float(r.volume)}
        for r in rows
    ])

    # Run detection in thread pool (CPU-bound)
    import asyncio
    from functools import partial

    def _run(df: pd.DataFrame) -> "EWResult":  # noqa: F821
        atr_ser = ta.atr(df["high"], df["low"], df["close"], length=14)
        sh_bool, _ = detect_swing_points(df["high"], order=5, atr_filter=0.5, atr_series=atr_ser)
        _, sl_bool = detect_swing_points(df["low"], order=5, atr_filter=0.5, atr_series=atr_ser)
        sh_idx = np.where(sh_bool)[0]
        sl_idx = np.where(sl_bool)[0]
        return detect_elliott_waves(df, sh_idx, sl_idx)

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, partial(_run, df))

    if result.best_wave is None:
        return EWDetectionResponse(symbol=symbol.upper())

    return EWDetectionResponse(
        symbol=symbol.upper(),
        wave_type=result.best_wave.wave_type,
        direction=result.best_wave.direction,
        current_position=result.current_position,
        confidence=round(result.confidence, 4),
        waves=[
            EWWavePointResponse(
                time=wp.time, price=wp.price,
                label=wp.label, bar_index=wp.bar_index,
            )
            for wp in result.best_wave.waves
        ],
    )
```

**Step 3: Register the endpoint**

Check `backend/app/main.py` — the patterns router should already be included. The new endpoint is on the same router so no registration needed.

**Step 4: Manual smoke test**

```bash
cd backend && uvicorn app.main:app --reload &
sleep 2
curl -s "http://localhost:8000/api/patterns/elliott-wave/AAPL?timeframe=1d" | python3 -m json.tool | head -30
# Kill the server: pkill -f uvicorn
```
Expected: JSON with `wave_type`, `waves` array, or `{"symbol":"AAPL","wave_type":null,...}`.

**Step 5: Commit**

```bash
cd backend && git add app/schemas/patterns.py app/api/patterns.py
git commit -m "feat: GET /api/patterns/elliott-wave/{symbol} endpoint"
```

---

## Task 5: Frontend Types + API Hook

**Files:**
- Modify: `frontend/src/types/index.ts`
- Create: `frontend/src/hooks/useEWPatterns.ts`
- Modify: `frontend/src/api/index.ts` (or wherever API calls live)

**Step 1: Add types to `frontend/src/types/index.ts`**

Append after the existing `ChartPatternDetection` interface:

```typescript
export interface EWWavePoint {
  time: string
  price: number
  label: string
  bar_index: number
}

export interface EWDetection {
  symbol: string
  wave_type: 'impulse' | 'corrective' | null
  direction: 'bullish' | 'bearish' | null
  current_position: string | null
  confidence: number
  waves: EWWavePoint[]
}
```

**Step 2: Add API call**

Find the API client file. Check `frontend/src/api/`:
```bash
ls frontend/src/api/
```

Add to the appropriate file (e.g. `frontend/src/api/index.ts` or `frontend/src/api/patterns.ts`):

```typescript
import type { EWDetection } from '../types'

export async function getEWDetection(
  symbol: string,
  timeframe: string = '1d',
): Promise<EWDetection> {
  const res = await fetch(`/api/patterns/elliott-wave/${symbol}?timeframe=${timeframe}`)
  if (!res.ok) throw new Error(`EW fetch failed: ${res.status}`)
  return res.json()
}
```

**Step 3: Create hook**

Create `frontend/src/hooks/useEWPatterns.ts`:

```typescript
import { useQuery } from '@tanstack/react-query'
import { getEWDetection } from '../api'
import type { EWDetection } from '../types'

export function useEWPatterns(symbol: string, timeframe: string = '1d') {
  return useQuery<EWDetection>({
    queryKey: ['ew-patterns', symbol, timeframe],
    queryFn: () => getEWDetection(symbol, timeframe),
    staleTime: 5 * 60 * 1000,   // 5 min
    enabled: !!symbol,
  })
}
```

**Step 4: Commit**

```bash
cd frontend && git add src/types/index.ts src/hooks/useEWPatterns.ts src/api/
git commit -m "feat: EWDetection types + useEWPatterns hook"
```

---

## Task 6: ChartControls — Add `waves` Toggle

**Files:**
- Modify: `frontend/src/components/stock/ChartControls.tsx`
- Modify: `frontend/src/__tests__/ChartControls.test.tsx`

**Step 1: Write failing tests**

In `frontend/src/__tests__/ChartControls.test.tsx`, find the test for "renders all overlay keys" and add/update:

```typescript
it('renders the waves toggle button', () => {
  const overlays = { ...DEFAULT_OVERLAYS, waves: true }
  render(<ChartControls overlays={overlays} onToggle={vi.fn()} onReset={vi.fn()} />)
  expect(screen.getByRole('button', { name: /EW Waves/i })).toBeInTheDocument()
})

it('fires onToggle with "waves" when waves button clicked', () => {
  const onToggle = vi.fn()
  const overlays = { ...DEFAULT_OVERLAYS, waves: true }
  render(<ChartControls overlays={overlays} onToggle={onToggle} onReset={vi.fn()} />)
  fireEvent.click(screen.getByRole('button', { name: /EW Waves/i }))
  expect(onToggle).toHaveBeenCalledWith('waves')
})
```

**Step 2: Run to verify they fail**

```bash
cd frontend && npm test -- --run src/__tests__/ChartControls.test.tsx 2>&1 | tail -20
```
Expected: FAIL (button not found, `waves` not in `OverlayKey`).

**Step 3: Update `ChartControls.tsx`**

```typescript
// Change:
export type OverlayKey = 'ema21' | 'ema50' | 'ema200' | 'supertrend' | 'volume' | 'patterns'

// To:
export type OverlayKey = 'ema21' | 'ema50' | 'ema200' | 'supertrend' | 'volume' | 'patterns' | 'waves'
```

```typescript
// In DEFAULT_OVERLAYS, add:
waves: true,
```

```typescript
// In BUTTON_LABELS, add:
waves: 'EW Waves',
```

```typescript
// In OVERLAY_KEYS, add:
const OVERLAY_KEYS: OverlayKey[] = ['ema21', 'ema50', 'ema200', 'supertrend', 'volume', 'patterns', 'waves']
```

**Step 4: Run tests**

```bash
cd frontend && npm test -- --run src/__tests__/ChartControls.test.tsx
```
Expected: All tests PASS.

**Step 5: Commit**

```bash
cd frontend && git add src/components/stock/ChartControls.tsx src/__tests__/ChartControls.test.tsx
git commit -m "feat: add EW Waves toggle to ChartControls"
```

---

## Task 7: ElliottWaveBanner Component

**Files:**
- Create: `frontend/src/components/stock/ElliottWaveBanner.tsx`
- Create: `frontend/src/__tests__/ElliottWaveBanner.test.tsx`

**Step 1: Write failing tests**

Create `frontend/src/__tests__/ElliottWaveBanner.test.tsx`:

```typescript
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ElliottWaveBanner } from '../components/stock/ElliottWaveBanner'
import type { EWDetection } from '../types'

const BULLISH_W3: EWDetection = {
  symbol: 'AAPL',
  wave_type: 'impulse',
  direction: 'bullish',
  current_position: 'wave_3',
  confidence: 0.82,
  waves: [],
}

const NO_WAVE: EWDetection = {
  symbol: 'AAPL',
  wave_type: null,
  direction: null,
  current_position: null,
  confidence: 0.0,
  waves: [],
}

describe('ElliottWaveBanner', () => {
  it('renders nothing when wave_type is null', () => {
    const { container } = render(<ElliottWaveBanner detection={NO_WAVE} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows Impulse label', () => {
    render(<ElliottWaveBanner detection={BULLISH_W3} />)
    expect(screen.getByText(/Impulse/i)).toBeInTheDocument()
  })

  it('shows Bullish direction badge', () => {
    render(<ElliottWaveBanner detection={BULLISH_W3} />)
    expect(screen.getByText(/Bullish/i)).toBeInTheDocument()
  })

  it('shows current wave position', () => {
    render(<ElliottWaveBanner detection={BULLISH_W3} />)
    expect(screen.getByText(/Wave 3/i)).toBeInTheDocument()
  })

  it('shows confidence as percentage', () => {
    render(<ElliottWaveBanner detection={BULLISH_W3} />)
    expect(screen.getByText(/82%/)).toBeInTheDocument()
  })

  it('shows red badge for bearish direction', () => {
    const bearish: EWDetection = { ...BULLISH_W3, direction: 'bearish' }
    render(<ElliottWaveBanner detection={bearish} />)
    const badge = screen.getByText(/Bearish/i)
    expect(badge.className).toMatch(/red/)
  })
})
```

**Step 2: Run to verify they fail**

```bash
cd frontend && npm test -- --run src/__tests__/ElliottWaveBanner.test.tsx 2>&1 | tail -10
```
Expected: `Cannot find module '.../ElliottWaveBanner'`.

**Step 3: Create `ElliottWaveBanner.tsx`**

Create `frontend/src/components/stock/ElliottWaveBanner.tsx`:

```typescript
import type { EWDetection } from '../../types'

interface Props {
  detection: EWDetection | undefined
}

function formatPosition(pos: string | null): string {
  if (!pos) return ''
  return pos
    .replace('wave_', 'Wave ')
    .replace('_complete', ' (Complete)')
    .toUpperCase()
    .replace('WAVE ', 'Wave ')
}

export function ElliottWaveBanner({ detection }: Props) {
  if (!detection || detection.wave_type === null) return null

  const isBullish = detection.direction === 'bullish'
  const directionClass = isBullish ? 'text-green-400 bg-green-400/10' : 'text-red-400 bg-red-400/10'
  const directionLabel = isBullish ? 'Bullish' : 'Bearish'
  const waveTypeLabel = detection.wave_type === 'impulse' ? 'Impulse' : 'Corrective'

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded bg-gray-800/60 text-xs mb-2">
      <span className="font-semibold text-gray-300">Elliott Wave</span>
      <span className="text-gray-400">{waveTypeLabel}</span>
      <span className={`px-1.5 py-0.5 rounded font-medium ${directionClass}`}>
        {directionLabel}
      </span>
      {detection.current_position && (
        <span className="text-gray-300 font-medium">
          {formatPosition(detection.current_position)}
        </span>
      )}
      <span className="ml-auto text-gray-500">
        {Math.round(detection.confidence * 100)}%
      </span>
    </div>
  )
}
```

**Step 4: Run tests**

```bash
cd frontend && npm test -- --run src/__tests__/ElliottWaveBanner.test.tsx
```
Expected: All 6 tests PASS.

**Step 5: Commit**

```bash
cd frontend && git add src/components/stock/ElliottWaveBanner.tsx src/__tests__/ElliottWaveBanner.test.tsx
git commit -m "feat: ElliottWaveBanner component"
```

---

## Task 8: Wave Overlay on CandlestickChart

**Files:**
- Modify: `frontend/src/components/stock/CandlestickChart.tsx`
- Modify: `frontend/src/__tests__/CandlestickChart.test.tsx` (or new test file)
- Create: `frontend/src/__tests__/drawEWOverlay.test.ts`

**Step 1: Write failing tests**

Create `frontend/src/__tests__/drawEWOverlay.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { drawEWOverlay } from '../components/stock/CandlestickChart'
import type { EWWavePoint } from '../types'

function makeCtx() {
  return {
    clearRect: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    stroke: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    fillText: vi.fn(),
    strokeStyle: '' as string,
    fillStyle: '' as string,
    lineWidth: 1 as number,
    font: '' as string,
  }
}

const WAVES: EWWavePoint[] = [
  { time: '2024-01-01', price: 100, label: '0', bar_index: 0 },
  { time: '2024-01-10', price: 200, label: '1', bar_index: 10 },
  { time: '2024-01-15', price: 150, label: '2', bar_index: 15 },
  { time: '2024-01-25', price: 310, label: '3', bar_index: 25 },
  { time: '2024-02-01', price: 250, label: '4', bar_index: 30 },
  { time: '2024-02-10', price: 350, label: '5', bar_index: 40 },
]

function makeCoords(waves: EWWavePoint[]) {
  const map = new Map(waves.map((w, i) => [w.time, i * 50]))
  const timeToCoord = (t: string) => map.get(t) ?? null
  const priceToCoord = (p: number) => 400 - p  // simple linear
  return { timeToCoord, priceToCoord }
}

describe('drawEWOverlay', () => {
  let ctx: ReturnType<typeof makeCtx>
  let timeToCoord: (t: string) => number | null
  let priceToCoord: (p: number) => number | null

  beforeEach(() => {
    ctx = makeCtx()
    const coords = makeCoords(WAVES)
    timeToCoord = coords.timeToCoord
    priceToCoord = coords.priceToCoord
  })

  it('calls clearRect', () => {
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, 800, 420, null, timeToCoord, priceToCoord)
    expect(ctx.clearRect).toHaveBeenCalledWith(0, 0, 800, 420)
  })

  it('draws nothing extra when waves is null', () => {
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, 800, 420, null, timeToCoord, priceToCoord)
    expect(ctx.moveTo).not.toHaveBeenCalled()
  })

  it('calls moveTo then multiple lineTo for the polyline', () => {
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, 800, 420, WAVES, timeToCoord, priceToCoord, 'bullish')
    expect(ctx.moveTo).toHaveBeenCalledTimes(1)
    expect(ctx.lineTo).toHaveBeenCalledTimes(WAVES.length - 1)
  })

  it('draws one label per wave point', () => {
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, 800, 420, WAVES, timeToCoord, priceToCoord, 'bullish')
    expect(ctx.fillText).toHaveBeenCalledTimes(WAVES.length)
  })

  it('skips wave point when timeToCoordinate returns null', () => {
    const nullCoord = () => null
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, 800, 420, WAVES, nullCoord, priceToCoord, 'bullish')
    expect(ctx.moveTo).not.toHaveBeenCalled()
  })
})
```

**Step 2: Run to verify they fail**

```bash
cd frontend && npm test -- --run src/__tests__/drawEWOverlay.test.ts 2>&1 | tail -10
```
Expected: `drawEWOverlay is not exported from CandlestickChart`.

**Step 3: Export `drawEWOverlay` from `CandlestickChart.tsx`**

Add the exported function to `CandlestickChart.tsx` (after `drawDetectionOverlays`):

```typescript
export function drawEWOverlay(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  waves: EWWavePoint[] | null,
  timeToCoordinate: (time: string) => number | null,
  priceToCoordinate: (price: number) => number | null,
  direction: 'bullish' | 'bearish' | null = null,
): void {
  ctx.clearRect(0, 0, width, height)
  if (!waves || waves.length < 2) return

  // Resolve coordinates for all wave points
  const coords: Array<{ x: number; y: number; label: string } | null> = waves.map((w) => {
    const x = timeToCoordinate(w.time)
    const y = priceToCoordinate(w.price)
    if (x === null || y === null) return null
    return { x, y, label: w.label }
  })

  if (coords.some((c) => c === null)) return   // skip if any point unresolvable

  const color = direction === 'bullish'
    ? 'rgba(34, 197, 94, 0.9)'
    : direction === 'bearish'
      ? 'rgba(239, 68, 68, 0.9)'
      : 'rgba(150, 150, 150, 0.9)'

  // Draw polyline
  ctx.strokeStyle = color
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.moveTo(coords[0]!.x, coords[0]!.y)
  for (let i = 1; i < coords.length; i++) {
    ctx.lineTo(coords[i]!.x, coords[i]!.y)
  }
  ctx.stroke()

  // Draw labels
  ctx.font = '10px sans-serif'
  ctx.fillStyle = color
  for (const pt of coords) {
    if (!pt) continue
    ctx.beginPath()
    ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillText(pt.label, pt.x + 5, pt.y - 5)
  }
}
```

Also add the `EWWavePoint` import at the top of the file:
```typescript
import type { ..., EWWavePoint } from '../../types'
```

**Step 4: Add second canvas to `CandlestickChart` component**

In the `useEffect` in `CandlestickChart.tsx`, after the existing detection canvas block, add an EW canvas:

The component needs new props: `ewWaves?: EWWavePoint[] | null`, `ewDirection?: 'bullish' | 'bearish' | null`.

Update the `Props` interface:
```typescript
interface Props {
  data: OHLCVResponse
  height?: number
  detections?: ChartPatternDetection[]
  overlays?: Partial<OverlayToggles>
  ewWaves?: EWWavePoint[] | null
  ewDirection?: 'bullish' | 'bearish' | null
}
```

In `useEffect`, after the detection canvas block (before the ResizeObserver):

```typescript
    // ── EW wave canvas overlay (z-index: 4) ──────────────────────────────────
    let ewCanvas: HTMLCanvasElement | null = null
    const ewCanvasRef = { current: null as HTMLCanvasElement | null }
    if (ewWaves !== undefined) {
      ewCanvas = document.createElement('canvas')
      ewCanvas.style.position = 'absolute'
      ewCanvas.style.top = '0'
      ewCanvas.style.left = '0'
      ewCanvas.style.pointerEvents = 'none'
      ewCanvas.style.zIndex = '4'
      container.appendChild(ewCanvas)
      ewCanvasRef.current = ewCanvas

      const redrawEW = () => {
        const canvas = ewCanvasRef.current
        if (!canvas) return
        const ctx = canvas.getContext('2d')
        if (!ctx) return
        canvas.width = container.clientWidth
        canvas.height = height
        drawEWOverlay(ctx, canvas.width, canvas.height, ewWaves ?? null, timeToCoord, priceToCoord, ewDirection ?? null)
      }
      redrawEW()
      chart.timeScale().subscribeVisibleTimeRangeChange(redrawEW)
    }
```

Add cleanup in return():
```typescript
      if (ewCanvas && ewCanvas.parentNode) {
        ewCanvas.parentNode.removeChild(ewCanvas)
      }
```

Add `ewWaves` and `ewDirection` to the `useEffect` dependency array.

Also handle `overlays.waves` visibility in the second `useEffect`:
```typescript
    // In the overlays useEffect, add:
    if (overlays.waves !== undefined && ewCanvasRef.current) {
      ewCanvasRef.current.style.display = overlays.waves ? '' : 'none'
    }
```

Wait — `ewCanvasRef` is defined inside the first `useEffect`. To share it across both effects, promote it to a module-level ref. Add:
```typescript
const ewCanvasRef = useRef<HTMLCanvasElement | null>(null)
```
alongside `canvasRef` at the component level. Update the EW canvas creation to use `ewCanvasRef.current = ewCanvas`, and cleanup to clear `ewCanvasRef.current = null`.

**Step 5: Run tests**

```bash
cd frontend && npm test -- --run src/__tests__/drawEWOverlay.test.ts
cd frontend && npm test -- --run src/__tests__/CandlestickChart.test.tsx
```
Expected: All PASS.

**Step 6: Commit**

```bash
cd frontend && git add src/components/stock/CandlestickChart.tsx src/__tests__/drawEWOverlay.test.ts
git commit -m "feat: EW wave polyline canvas overlay on CandlestickChart"
```

---

## Task 9: ResultsTable EW Column

**Files:**
- Modify: `frontend/src/components/scanner/ResultsTable.tsx`
- Modify: `frontend/src/types/index.ts` (add ew fields to ScannerResult)

**Step 1: Add EW signals to ScannerResult type**

`ScannerResult` already has `signals: Record<string, number>`. No type change needed — we read from `signals.ew_wave3_active`, `signals.ew_wave5_active`, `signals.ew_corrective_abc`.

**Step 2: Add EW column to ResultsTable**

In `frontend/src/components/scanner/ResultsTable.tsx`:

2a. Add column header after the "Patterns" `<th>`:
```tsx
<th className="px-3 py-2 text-left">EW</th>
```

2b. Add column cell after the patterns cell. The EW position is derived from signals:

```tsx
<td className="px-3 py-2.5">
  {(() => {
    const sigs = r.signals ?? {}
    const w3 = sigs.ew_wave3_active ?? 0
    const w5 = sigs.ew_wave5_active ?? 0
    const abc = sigs.ew_corrective_abc ?? 0
    const quality = sigs.ew_ratio_quality ?? 0

    if (quality < 0.1) return <span className="text-gray-600 text-xs">—</span>

    let label = ''
    let colorClass = 'text-gray-400'
    if (w3 > 0.5) { label = 'W3 ↑'; colorClass = 'text-green-400' }
    else if (w5 > 0.3) { label = 'W5 ↑'; colorClass = 'text-green-300' }
    else if (abc < -0.1) { label = 'ABC ↓'; colorClass = 'text-red-400' }
    else { label = `EW ${Math.round(quality * 100)}%`; colorClass = 'text-gray-400' }

    return (
      <span
        className={`text-xs font-medium ${colorClass}`}
        title={`EW quality: ${Math.round(quality * 100)}%`}
      >
        {label}
      </span>
    )
  })()}
</td>
```

**Step 3: Check existing tests**

```bash
cd frontend && npm test -- --run src/__tests__/ResultsTable.test.tsx
```
If tests fail because they assert on column count or don't include `signals`, add `signals: {}` to test fixture rows.

**Step 4: Commit**

```bash
cd frontend && git add src/components/scanner/ResultsTable.tsx
git commit -m "feat: EW column in ResultsTable scanner"
```

---

## Task 10: StockDetailPage Wiring

**Files:**
- Modify: `frontend/src/pages/StockDetailPage.tsx`

**Step 1: Wire up the hook and components**

In `frontend/src/pages/StockDetailPage.tsx`:

1a. Add imports:
```typescript
import { useEWPatterns } from '../hooks/useEWPatterns'
import { ElliottWaveBanner } from '../components/stock/ElliottWaveBanner'
```

1b. Inside the component, after existing hooks:
```typescript
const { data: ewData } = useEWPatterns(symbol, chartTimeframe)
```

1c. Pass `ewWaves` and `ewDirection` to `CandlestickChart`:
```tsx
<CandlestickChart
  ref={chartRef}
  data={ohlcvData}
  detections={patternData?.detections}
  overlays={overlays}
  ewWaves={ewData?.waves ?? null}
  ewDirection={ewData?.direction ?? null}
/>
```

1d. Add `ElliottWaveBanner` below `ChartPatternsBanner`:
```tsx
<ElliottWaveBanner detection={ewData} />
```

**Step 2: Verify in browser**

```bash
cd frontend && npm run dev
```
Open a stock detail page. Confirm:
- EW banner appears (or is hidden when no wave detected)
- Wave polyline appears on chart when EW detected
- "EW Waves" toggle hides/shows the polyline

**Step 3: Commit**

```bash
cd frontend && git add src/pages/StockDetailPage.tsx
git commit -m "feat: wire up ElliottWaveBanner and wave overlay in StockDetailPage"
```

---

## Task 11: Final Test Run and Cleanup

**Step 1: Run all backend unit tests**

```bash
cd backend && uv run --extra dev python -m pytest -m unit -v 2>&1 | tail -30
```
Expected: All pass (previous count was 314 + new EW tests).

**Step 2: Run all frontend tests**

```bash
cd frontend && npm test -- --run 2>&1 | tail -20
```
Expected: All pass.

**Step 3: Run TA validation tests**

```bash
cd backend && uv run --extra dev python -m pytest -m ta_validation -v
```
Expected: 13 pass.

**Step 4: Final commit (if any cleanup needed)**

```bash
git add -A && git commit -m "chore: Elliott Wave P1 final cleanup"
```
