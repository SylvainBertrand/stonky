# P1 Elliott Wave Detection — Design

**Date:** 2026-03-04
**Status:** Approved

## Summary

Implement Elliott Wave (EW) detection inline in the scanner pipeline using a custom hybrid greedy + Fibonacci-ratio algorithm. Surface results in the frontend via a banner, chart overlay, toggle control, and scanner table column.

## Architecture

```
swing_points.py (existing)
        ↓
elliott_wave.py  (new — detect_elliott_waves)
        ↓
pipeline.py      (inline in run_analysis, like harmonics)
        ↓
pattern_detections table  (existing — geometry JSONB)
        ↓
GET /api/patterns/elliott-wave/{symbol}  (new endpoint)
        ↓
ElliottWaveBanner + CandlestickChart wave overlay
```

## Backend

### New module: `backend/app/analysis/indicators/elliott_wave.py`

**Core types:**

```python
@dataclass
class WavePoint:
    time: str       # bar timestamp
    price: float    # pivot price
    label: str      # "0","1","2","3","4","5" or "A","B","C"
    bar_index: int  # index into bars array

@dataclass
class WaveSequence:
    wave_type: Literal['impulse', 'corrective']
    direction: Literal['bullish', 'bearish']
    waves: list[WavePoint]  # 6 pts (impulse) or 4 pts (corrective)
    confidence: float       # 0–1 Fibonacci ratio quality

@dataclass
class EWResult:
    best_wave: WaveSequence | None
    current_position: str | None  # "wave_3", "wave_5", "wave_C", etc.
    confidence: float
```

**Detection algorithm (greedy forward scan):**

1. Receive swing highs/lows from the existing swing_points arrays (already computed in run_analysis)
2. Interleave swing highs and lows to form alternating pivot sequence
3. For each candidate 6-point window (5-wave impulse):
   - Validate EW rules:
     - Wave 2 retraces < 100% of Wave 1 (W2 price never crosses W0)
     - Wave 3 is not the shortest among W1, W3, W5 amplitudes
     - Wave 4 does not overlap Wave 1 price territory (non-diagonal)
   - Score Fibonacci ratio quality:
     - W2 retrace: target 61.8% of W1 (±20% tolerance)
     - W3 extension: target 161.8% of W1
     - W4 retrace: target 38.2% of W3
     - W5 = W1 amplitude ±30%
   - confidence = mean(ratio_scores) × rule_pass_factor
4. Also scan for 3-wave corrective (A-B-C) in 4-point windows
5. Return best sequence found in last 120 bars (same window as YOLO)
6. Determine `current_position` based on last bar's position within the best wave

**Signals emitted** (feed into `pattern` category score):
- `ew_wave3_active`: +1.0 if last bar is within wave 3
- `ew_wave5_active`: +0.5 if in wave 5
- `ew_corrective_abc`: −0.3 if in corrective A-B-C
- `ew_ratio_quality`: 0–1 raw Fibonacci quality (always emitted, 0 if no wave found)

### Pipeline integration

`pipeline.py` — in `run_analysis()` after harmonics:
```python
from .indicators.elliott_wave import detect_elliott_waves, compute_ew_signals

ew_result = detect_elliott_waves(df, swing_highs_idx, swing_lows_idx)
signals.update(compute_ew_signals(ew_result))
```

Store best wave in `pattern_detections`:
- `pattern_type = 'chart_pattern'`
- `pattern_name = 'elliott_wave_impulse'` or `'elliott_wave_corrective'` (in geometry)
- `geometry JSONB`: `{"ew_type": "impulse", "direction": "bullish", "current_position": "wave_3", "confidence": 0.82, "waves": [{"time": ..., "price": ..., "label": "0"}, ...]}`

### API endpoint

`GET /api/patterns/elliott-wave/{symbol}?timeframe=1d`

Response:
```json
{
  "symbol": "AAPL",
  "wave_type": "impulse",
  "direction": "bullish",
  "current_position": "wave_3",
  "confidence": 0.82,
  "waves": [
    {"time": "2024-01-10", "price": 180.0, "label": "0"},
    {"time": "2024-01-15", "price": 195.0, "label": "1"},
    ...
  ]
}
```

Returns `{"symbol": ..., "wave_type": null, ...}` when no EW detected.

## Frontend

### New components

**`ElliottWaveBanner`** (`src/components/stock/ElliottWaveBanner.tsx`):
- Compact banner below `ChartPatternsBanner` on `StockDetailPage`
- Shows: wave type, direction badge (Bullish/Bearish), current position ("In Wave 3"), confidence %
- Hidden when `wave_type === null`

**Wave overlay on `CandlestickChart`**:
- Second canvas at `z-index: 4` (above existing detection canvas at z-index: 3)
- Draws polyline through wave pivot points
- Colored line: green=bullish, red=bearish
- Circle + number label at each pivot
- Toggled via `overlays.waves`

### `ChartControls` update

Add 7th toggle: `waves` (label: "EW Waves").
- `OverlayKey` gains `'waves'`
- `DEFAULT_OVERLAYS` gains `waves: true`

### `ResultsTable` update

New EW column:
- Shows current wave position: "W3 ↑", "W5 ↑", "ABC ↓", or "—"
- Color-coded by direction
- Tooltip: confidence percentage

### Data fetching

New hook `useEWPatterns(symbol, timeframe)` in `src/hooks/useEWPatterns.ts`:
- TanStack Query, hits `GET /api/patterns/elliott-wave/{symbol}`
- Shared between `ElliottWaveBanner` and chart overlay

## Testing

### Backend (TDD)
- Unit tests: `detect_elliott_waves` on synthetic swing sequences
  - Valid 5-wave bullish impulse detected
  - Rule violations correctly rejected (W2 > 100%, W3 shortest, W4 overlap)
  - Fibonacci ratio quality scoring
  - Corrective A-B-C detection
  - No swings → returns EWResult with best_wave=None
- Signal tests: `compute_ew_signals` emits correct keys/values
- API tests: GET endpoint returns correct shape

### Frontend (TDD)
- `ElliottWaveBanner` renders detected waves, hidden when none
- `ChartControls` renders 7th toggle, fires onToggle with 'waves'
- Canvas wave overlay draws polyline (unit test on drawing function)
- `ResultsTable` renders EW column correctly

## Files Changed

**New:**
- `backend/app/analysis/indicators/elliott_wave.py`
- `backend/tests/unit/test_elliott_wave.py`
- `frontend/src/components/stock/ElliottWaveBanner.tsx`
- `frontend/src/__tests__/ElliottWaveBanner.test.tsx`
- `frontend/src/hooks/useEWPatterns.ts`

**Modified:**
- `backend/app/analysis/pipeline.py`
- `backend/app/api/patterns.py`
- `backend/app/schemas/patterns.py`
- `frontend/src/components/stock/CandlestickChart.tsx`
- `frontend/src/components/stock/ChartControls.tsx`
- `frontend/src/__tests__/ChartControls.test.tsx`
- `frontend/src/__tests__/CandlestickChart.test.tsx`
- `frontend/src/pages/StockDetailPage.tsx`
- `frontend/src/components/ResultsTable.tsx`
- `frontend/src/types/index.ts`
