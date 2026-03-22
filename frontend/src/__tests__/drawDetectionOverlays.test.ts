import { beforeEach, describe, expect, it, vi } from 'vitest'
import { drawDetectionOverlays } from '../components/stock/CandlestickChart'
import type { ChartPatternDetection, OHLCVBar } from '../types'

// ── Mock canvas context ────────────────────────────────────────────────────

function makeCtx() {
  return {
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    strokeRect: vi.fn(),
    fillText: vi.fn(),
    fillStyle: '' as string,
    strokeStyle: '' as string,
    lineWidth: 1 as number,
    font: '' as string,
  }
}

// ── Fixtures ───────────────────────────────────────────────────────────────

function makeBars(count: number): OHLCVBar[] {
  return Array.from({ length: count }, (_, i) => ({
    time: `2024-01-${String(i + 1).padStart(2, '0')}`,
    open: 100,
    high: 110,
    low: 90,
    close: 105,
    volume: 1_000_000,
  }))
}

// timeToCoordinate that maps times to linear pixel positions (time string → index * 5)
function linearCoord(bars: OHLCVBar[]): (time: string | number) => number | null {
  const map = new Map(bars.map((b, i) => [b.time, i * 5]))
  return (time) => map.get(time) ?? null
}

const CANVAS_W = 800
const CANVAS_H = 420

const BULLISH: ChartPatternDetection = {
  pattern: 'bull_flag',
  direction: 'bullish',
  confidence: 0.81,
  bar_start: 10,
  bar_end: 20,
}

const BEARISH: ChartPatternDetection = {
  pattern: 'head_and_shoulders',
  direction: 'bearish',
  confidence: 0.67,
  bar_start: 30,
  bar_end: 50,
}

const NEUTRAL: ChartPatternDetection = {
  pattern: 'triangle',
  direction: 'neutral',
  confidence: 0.55,
  bar_start: 5,
  bar_end: 15,
}

// ── Tests ──────────────────────────────────────────────────────────────────

describe('drawDetectionOverlays', () => {
  let ctx: ReturnType<typeof makeCtx>
  let bars: OHLCVBar[]
  let toCoord: (time: string | number) => number | null

  beforeEach(() => {
    ctx = makeCtx()
    bars = makeBars(60)
    toCoord = linearCoord(bars)
  })

  it('clears the entire canvas before drawing', () => {
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [], 0, bars, toCoord)
    expect(ctx.clearRect).toHaveBeenCalledWith(0, 0, CANVAS_W, CANVAS_H)
  })

  it('draws no rectangles when detections array is empty', () => {
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [], 0, bars, toCoord)
    expect(ctx.fillRect).not.toHaveBeenCalled()
    expect(ctx.strokeRect).not.toHaveBeenCalled()
  })

  it('calls fillRect once per detection', () => {
    drawDetectionOverlays(
      ctx as unknown as CanvasRenderingContext2D,
      CANVAS_W, CANVAS_H,
      [BULLISH, BEARISH],
      0, bars, toCoord,
    )
    expect(ctx.fillRect).toHaveBeenCalledTimes(2)
  })

  it('bullish detection fills with green color', () => {
    const fills: string[] = []
    Object.defineProperty(ctx, 'fillStyle', {
      set(v: string) { fills.push(v) },
      get() { return fills[fills.length - 1] ?? '' },
    })
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, toCoord)
    // The fill color set before fillRect should be the green rgba
    const fillColorBeforeRect = fills[fills.indexOf('rgba(0, 255, 100, 0.12)')]
    expect(fillColorBeforeRect).toBe('rgba(0, 255, 100, 0.12)')
  })

  it('bearish detection fills with red color', () => {
    const fills: string[] = []
    Object.defineProperty(ctx, 'fillStyle', {
      set(v: string) { fills.push(v) },
      get() { return fills[fills.length - 1] ?? '' },
    })
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BEARISH], 0, bars, toCoord)
    expect(fills).toContain('rgba(255, 60, 60, 0.12)')
  })

  it('neutral detection fills with gray color', () => {
    const fills: string[] = []
    Object.defineProperty(ctx, 'fillStyle', {
      set(v: string) { fills.push(v) },
      get() { return fills[fills.length - 1] ?? '' },
    })
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [NEUTRAL], 0, bars, toCoord)
    expect(fills).toContain('rgba(150, 150, 150, 0.10)')
  })

  it('rectangle spans full canvas height (y=0, h=canvasHeight)', () => {
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, toCoord)
    const [, y, , h] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    expect(y).toBe(0)
    expect(h).toBe(CANVAS_H)
  })

  it('rectangle x position comes from timeToCoordinate of bar_start', () => {
    // With linearCoord: bar_start=10 → time='2024-01-11' → coord = 10*5 = 50
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, toCoord)
    const [x] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    const expectedX = toCoord(bars[BULLISH.bar_start].time)!
    expect(x).toBe(expectedX)
  })

  it('rectangle width equals x2 minus x1', () => {
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, toCoord)
    const [x, , w] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    const x1 = toCoord(bars[BULLISH.bar_start].time)!
    const x2 = toCoord(bars[BULLISH.bar_end].time)!
    expect(x).toBe(Math.min(x1, x2))
    expect(w).toBe(Math.abs(x2 - x1))
  })

  it('draws a border (strokeRect) for each detection', () => {
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, toCoord)
    expect(ctx.strokeRect).toHaveBeenCalledTimes(1)
  })

  it('border strokeRect uses same x/y/w/h as fillRect', () => {
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, toCoord)
    expect(ctx.strokeRect.mock.calls[0]).toEqual(ctx.fillRect.mock.calls[0])
  })

  it('draws label text with pattern name and confidence', () => {
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, toCoord)
    expect(ctx.fillText).toHaveBeenCalledTimes(1)
    const [text] = ctx.fillText.mock.calls[0] as [string, ...unknown[]]
    expect(text).toMatch(/Bull Flag/)
    expect(text).toMatch(/81%/)
  })

  it('label text is drawn near the top edge of the rectangle', () => {
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, toCoord)
    const [, , y] = ctx.fillText.mock.calls[0] as [string, number, number]
    // Should be near the top (y < 30)
    expect(y).toBeLessThan(30)
  })

  it('skips detection when bar_start is out of range of bars array', () => {
    const detection: ChartPatternDetection = { ...BULLISH, bar_start: 200, bar_end: 210 }
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [detection], 0, bars, toCoord)
    expect(ctx.fillRect).not.toHaveBeenCalled()
  })

  it('skips detection when timeToCoordinate returns null for bar_start', () => {
    const nullCoord = () => null
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, nullCoord)
    expect(ctx.fillRect).not.toHaveBeenCalled()
  })

  it('skips detection when timeToCoordinate returns null for bar_end', () => {
    const barEndTime = bars[BULLISH.bar_end].time
    const partialCoord = (time: string | number) => time === barEndTime ? null : (toCoord(time))
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], 0, bars, partialCoord)
    expect(ctx.fillRect).not.toHaveBeenCalled()
  })

  it('applies barOffset when looking up bar times', () => {
    // barOffset=5 means bar_start=10 → bars[5+10] = bars[15]
    const barOffset = 5
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [BULLISH], barOffset, bars, toCoord)
    const [x] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    const expectedX = toCoord(bars[barOffset + BULLISH.bar_start].time)!
    expect(x).toBe(expectedX)
  })

  // ── priceToCoordinate for tight vertical bounds ───────────────────────────

  it('uses priceToCoordinate for y-bounds when price_top/price_bottom are provided', () => {
    // priceToCoord maps: higher price → smaller canvas y (top of chart)
    // price_top=110 → y=80; price_bottom=90 → y=320
    const priceToCoord = (price: number) => price === 110 ? 80 : price === 90 ? 320 : null
    const detection: ChartPatternDetection = { ...BULLISH, price_top: 110, price_bottom: 90 }
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [detection], 0, bars, toCoord, priceToCoord)
    const [, y, , h] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    expect(y).toBe(80)   // min(80, 320)
    expect(h).toBe(240)  // abs(320 - 80)
  })

  it('falls back to full height (y=0, h=CANVAS_H) when price_top/price_bottom are absent', () => {
    const priceToCoord = (price: number) => price * 2
    const detection: ChartPatternDetection = { ...BULLISH }  // no price_top/price_bottom
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [detection], 0, bars, toCoord, priceToCoord)
    const [, y, , h] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    expect(y).toBe(0)
    expect(h).toBe(CANVAS_H)
  })

  it('falls back to full height when priceToCoordinate returns null for price_top', () => {
    const nullPriceToCoord = (_price: number) => null
    const detection: ChartPatternDetection = { ...BULLISH, price_top: 110, price_bottom: 90 }
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [detection], 0, bars, toCoord, nullPriceToCoord)
    const [, y, , h] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    expect(y).toBe(0)
    expect(h).toBe(CANVAS_H)
  })

  it('falls back to full height when priceToCoordinate is not provided', () => {
    const detection: ChartPatternDetection = { ...BULLISH, price_top: 110, price_bottom: 90 }
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [detection], 0, bars, toCoord)
    const [, y, , h] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    expect(y).toBe(0)
    expect(h).toBe(CANVAS_H)
  })

  it('falls back to full height when price_top is null (API serializes Python None as null)', () => {
    const priceToCoord = vi.fn((price: number) => price * 2)
    // Simulate what the API returns for old detections: price_top/price_bottom are null, not undefined
    const detection = { ...BULLISH, price_top: null, price_bottom: null } as unknown as ChartPatternDetection
    drawDetectionOverlays(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, [detection], 0, bars, toCoord, priceToCoord)
    const [, y, , h] = ctx.fillRect.mock.calls[0] as [number, number, number, number]
    expect(y).toBe(0)
    expect(h).toBe(CANVAS_H)
  })
})
