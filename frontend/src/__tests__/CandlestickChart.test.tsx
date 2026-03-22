import { render } from '@testing-library/react'
import { createRef } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { CandlestickChart } from '../components/stock/CandlestickChart'
import type { ChartHandle } from '../components/stock/CandlestickChart'
import type { ChartPatternDetection, OHLCVResponse } from '../types'
import type { OverlayToggles } from '../components/stock/ChartControls'

// ── Mocks ──────────────────────────────────────────────────────────────────

const mockSetMarkers = vi.fn()
const mockCandleSeries = {
  setData: vi.fn(),
  setMarkers: mockSetMarkers,
}
const mockSubscribeVisibleTimeRangeChange = vi.fn()
const mockTimeToCoordinate = vi.fn(() => 100)
const mockTimeScale = {
  fitContent: vi.fn(),
  timeToCoordinate: mockTimeToCoordinate,
  subscribeVisibleTimeRangeChange: mockSubscribeVisibleTimeRangeChange,
  unsubscribeVisibleTimeRangeChange: vi.fn(),
}
const mockLineSeries = { setData: vi.fn(), applyOptions: vi.fn() }
const mockHistogramSeries = { setData: vi.fn(), applyOptions: vi.fn() }
const mockChart = {
  addCandlestickSeries: vi.fn(() => mockCandleSeries),
  addHistogramSeries: vi.fn(() => mockHistogramSeries),
  addLineSeries: vi.fn(() => mockLineSeries),
  priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
  timeScale: vi.fn(() => mockTimeScale),
  applyOptions: vi.fn(),
  remove: vi.fn(),
}

vi.mock('lightweight-charts', () => ({
  createChart: vi.fn(() => mockChart),
}))

// jsdom doesn't implement canvas — silence the "not implemented" warning
HTMLCanvasElement.prototype.getContext = () => null

// ── Fixtures ───────────────────────────────────────────────────────────────

function makeOHLCV(barCount = 150, withEmas = false): OHLCVResponse {
  const bars = Array.from({ length: barCount }, (_, i) => ({
    time: `2024-${String(Math.floor(i / 30) + 1).padStart(2, '0')}-${String((i % 28) + 1).padStart(2, '0')}`,
    open: 100 + i,
    high: 105 + i,
    low: 95 + i,
    close: 102 + i,
    volume: 1_000_000,
  }))
  const emaPoints = withEmas
    ? bars.map((b) => ({ time: b.time, value: b.close }))
    : []
  return {
    symbol: 'AAPL',
    bars,
    has_more: false,
    overlays: {
      ema_21: emaPoints,
      ema_50: emaPoints,
      ema_200: emaPoints,
      supertrend: [],
    },
  }
}

const BULLISH_DETECTION: ChartPatternDetection = {
  pattern: 'bull_flag',
  direction: 'bullish',
  confidence: 0.81,
  bar_start: 90,
  bar_end: 115,
}

const BEARISH_DETECTION: ChartPatternDetection = {
  pattern: 'head_and_shoulders',
  direction: 'bearish',
  confidence: 0.67,
  bar_start: 10,
  bar_end: 80,
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('CandlestickChart', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders without crashing when detections prop is omitted', () => {
    const { container } = render(<CandlestickChart data={makeOHLCV()} />)
    expect(container.firstChild).toBeTruthy()
  })

  it('renders without crashing when detections is empty array', () => {
    const { container } = render(<CandlestickChart data={makeOHLCV()} detections={[]} />)
    expect(container.firstChild).toBeTruthy()
  })

  it('never calls setMarkers — canvas overlay provides the label, no arrow marker needed', () => {
    render(<CandlestickChart data={makeOHLCV()} detections={[BULLISH_DETECTION, BEARISH_DETECTION]} />)
    expect(mockSetMarkers).not.toHaveBeenCalled()
  })

  // ── Canvas overlay tests ─────────────────────────────────────────────────

  it('renders a canvas overlay element inside the chart container', () => {
    const { container } = render(<CandlestickChart data={makeOHLCV()} detections={[BULLISH_DETECTION]} />)
    const canvas = container.querySelector('canvas')
    expect(canvas).toBeTruthy()
  })

  it('canvas has pointer-events: none so it does not intercept mouse events', () => {
    const { container } = render(<CandlestickChart data={makeOHLCV()} detections={[BULLISH_DETECTION]} />)
    const canvas = container.querySelector('canvas')!
    expect(canvas.style.pointerEvents).toBe('none')
  })

  it('canvas is absolutely positioned to overlay the chart', () => {
    const { container } = render(<CandlestickChart data={makeOHLCV()} detections={[BULLISH_DETECTION]} />)
    const canvas = container.querySelector('canvas')!
    expect(canvas.style.position).toBe('absolute')
  })

  it('canvas has z-index 3 to sit above LW main (z-index:1) and crosshair (z-index:2) canvases', () => {
    const { container } = render(<CandlestickChart data={makeOHLCV()} detections={[BULLISH_DETECTION]} />)
    const canvas = container.querySelector('canvas')!
    expect(canvas.style.zIndex).toBe('3')
  })

  it('canvas is also rendered when detections is empty (ready for future content)', () => {
    const { container } = render(<CandlestickChart data={makeOHLCV()} detections={[]} />)
    const canvas = container.querySelector('canvas')
    expect(canvas).toBeTruthy()
  })

  it('subscribes to visible time range changes when detections are provided', () => {
    render(<CandlestickChart data={makeOHLCV()} detections={[BULLISH_DETECTION]} />)
    expect(mockSubscribeVisibleTimeRangeChange).toHaveBeenCalled()
  })

  it('subscribes to visible time range changes even with empty detections', () => {
    render(<CandlestickChart data={makeOHLCV()} detections={[]} />)
    expect(mockSubscribeVisibleTimeRangeChange).toHaveBeenCalled()
  })

  it('does not subscribe to visible time range changes when detections prop is omitted', () => {
    render(<CandlestickChart data={makeOHLCV()} />)
    expect(mockSubscribeVisibleTimeRangeChange).not.toHaveBeenCalled()
  })

  // ── Overlay visibility ────────────────────────────────────────────────────

  it('hiding volume calls applyOptions({ visible: false }) on volume series', () => {
    const overlays: OverlayToggles = {
      ema21: true, ema50: true, ema200: true, supertrend: true, volume: false, patterns: true, waves: true, forecast: false,
    }
    render(<CandlestickChart data={makeOHLCV()} overlays={overlays} />)
    expect(mockHistogramSeries.applyOptions).toHaveBeenCalledWith({ visible: false })
  })

  it('showing volume calls applyOptions({ visible: true }) on volume series', () => {
    const overlays: OverlayToggles = {
      ema21: true, ema50: true, ema200: true, supertrend: true, volume: true, patterns: true, waves: true, forecast: false,
    }
    render(<CandlestickChart data={makeOHLCV()} overlays={overlays} />)
    expect(mockHistogramSeries.applyOptions).toHaveBeenCalledWith({ visible: true })
  })

  it('hiding an EMA calls applyOptions({ visible: false }) on a line series', () => {
    const overlays: OverlayToggles = {
      ema21: false, ema50: true, ema200: true, supertrend: true, volume: true, patterns: true, waves: true, forecast: false,
    }
    render(<CandlestickChart data={makeOHLCV(150, true)} overlays={overlays} />)
    expect(mockLineSeries.applyOptions).toHaveBeenCalledWith({ visible: false })
  })

  // ── forwardRef / ChartHandle ──────────────────────────────────────────────

  it('exposes fitContent via ref', () => {
    const ref = createRef<ChartHandle>()
    render(<CandlestickChart ref={ref} data={makeOHLCV()} />)
    expect(typeof ref.current?.fitContent).toBe('function')
  })

  it('calling ref.fitContent() calls chart.timeScale().fitContent()', () => {
    const ref = createRef<ChartHandle>()
    render(<CandlestickChart ref={ref} data={makeOHLCV()} />)
    ref.current?.fitContent()
    expect(mockTimeScale.fitContent).toHaveBeenCalled()
  })
})
