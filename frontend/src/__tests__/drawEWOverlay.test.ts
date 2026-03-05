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
  const priceToCoord = (p: number) => 400 - p
  return { timeToCoord, priceToCoord }
}

const CANVAS_W = 800
const CANVAS_H = 420

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
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, null, timeToCoord, priceToCoord)
    expect(ctx.clearRect).toHaveBeenCalledWith(0, 0, CANVAS_W, CANVAS_H)
  })

  it('draws nothing extra when waves is null', () => {
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, null, timeToCoord, priceToCoord)
    expect(ctx.moveTo).not.toHaveBeenCalled()
  })

  it('calls moveTo then multiple lineTo for the polyline', () => {
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, WAVES, timeToCoord, priceToCoord, 'bullish')
    expect(ctx.moveTo).toHaveBeenCalledTimes(1)
    expect(ctx.lineTo).toHaveBeenCalledTimes(WAVES.length - 1)
  })

  it('draws one label per wave point', () => {
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, WAVES, timeToCoord, priceToCoord, 'bullish')
    expect(ctx.fillText).toHaveBeenCalledTimes(WAVES.length)
  })

  it('skips wave point when timeToCoordinate returns null for all', () => {
    const nullCoord = () => null
    drawEWOverlay(ctx as unknown as CanvasRenderingContext2D, CANVAS_W, CANVAS_H, WAVES, nullCoord, priceToCoord, 'bullish')
    expect(ctx.moveTo).not.toHaveBeenCalled()
  })
})
