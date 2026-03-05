import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import { createChart, type IChartApi, type ISeriesApi, type HistogramData, type LineData, type CandlestickData, type Time } from 'lightweight-charts'
import type { ChartPatternDetection, OHLCVBar, OHLCVResponse } from '../../types'
import type { OverlayToggles } from './ChartControls'

// Number of bars the YOLO chart renderer uses — bar_start/bar_end are indices into this window
const YOLO_CHART_BARS = 120

export interface ChartHandle {
  fitContent: () => void
}

interface Props {
  data: OHLCVResponse
  height?: number
  detections?: ChartPatternDetection[]
  overlays?: Partial<OverlayToggles>
}

// ── Pure drawing function (exported for unit testing) ──────────────────────────

export function drawDetectionOverlays(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  detections: ChartPatternDetection[],
  barOffset: number,
  bars: OHLCVBar[],
  timeToCoordinate: (time: string) => number | null,
  priceToCoordinate?: (price: number) => number | null,
): void {
  ctx.clearRect(0, 0, width, height)

  for (const det of detections) {
    const startBar = bars[barOffset + det.bar_start]
    const endBar = bars[barOffset + det.bar_end]
    if (!startBar || !endBar) continue

    const x1 = timeToCoordinate(startBar.time)
    const x2 = timeToCoordinate(endBar.time)
    if (x1 === null || x2 === null) continue

    const rectX = Math.min(x1, x2)
    const rectW = Math.abs(x2 - x1)

    // Vertical bounds: use price coords when available, else full canvas height
    let rectY = 0
    let rectH = height
    if (
      priceToCoordinate &&
      det.price_top != null &&
      det.price_bottom != null
    ) {
      const yTop = priceToCoordinate(det.price_top)
      const yBottom = priceToCoordinate(det.price_bottom)
      if (yTop !== null && yBottom !== null) {
        rectY = Math.min(yTop, yBottom)
        rectH = Math.abs(yBottom - yTop)
      }
    }

    const isBullish = det.direction === 'bullish'
    const isBearish = det.direction === 'bearish'

    // Filled region
    ctx.fillStyle = isBullish
      ? 'rgba(0, 255, 100, 0.12)'
      : isBearish
        ? 'rgba(255, 60, 60, 0.12)'
        : 'rgba(150, 150, 150, 0.10)'
    ctx.fillRect(rectX, rectY, rectW, rectH)

    // Border
    ctx.strokeStyle = isBullish
      ? 'rgba(0, 255, 100, 0.4)'
      : isBearish
        ? 'rgba(255, 60, 60, 0.4)'
        : 'rgba(150, 150, 150, 0.4)'
    ctx.lineWidth = 1
    ctx.strokeRect(rectX, rectY, rectW, rectH)

    // Label at top edge of the rectangle
    const label = det.pattern
      .split('_')
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(' ')
    ctx.font = '11px sans-serif'
    ctx.fillStyle = isBullish
      ? 'rgba(0, 255, 100, 0.8)'
      : isBearish
        ? 'rgba(255, 60, 60, 0.8)'
        : 'rgba(150, 150, 150, 0.8)'
    ctx.fillText(`${label} ${Math.round(det.confidence * 100)}%`, rectX + 4, rectY + 14)
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export const CandlestickChart = forwardRef<ChartHandle, Props>(function CandlestickChart(
  { data, height = 420, detections, overlays },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  // canvasRef is populated imperatively in useEffect AFTER createChart so it sits
  // above LW's own canvases in DOM order (z-index: 1 and z-index: 2).
  const canvasRef = useRef<HTMLCanvasElement | null>(null)

  // Series refs for overlay visibility control
  const ema21Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ema50Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const ema200Ref = useRef<ISeriesApi<'Line'> | null>(null)
  const supertrendRef = useRef<ISeriesApi<'Line'> | null>(null)
  const volumeRef = useRef<ISeriesApi<'Histogram'> | null>(null)

  useImperativeHandle(ref, () => ({
    fitContent: () => {
      chartRef.current?.timeScale().fitContent()
    },
  }))

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    // Clean up any previous chart
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    // ── Create chart ──────────────────────────────────────────────────────────
    const chart = createChart(container, {
      layout: {
        background: { color: '#0d1117' },
        textColor: '#8b949e',
      },
      grid: {
        vertLines: { color: '#21262d' },
        horzLines: { color: '#21262d' },
      },
      crosshair: {
        vertLine: { color: '#444d56' },
        horzLine: { color: '#444d56' },
      },
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: {
        borderColor: '#30363d',
        timeVisible: false,
      },
      width: container.clientWidth,
      height,
    })
    chartRef.current = chart

    // ── Candlestick series ────────────────────────────────────────────────────
    const candleSeries: ISeriesApi<'Candlestick'> = chart.addCandlestickSeries({
      upColor: '#22c55e',
      downColor: '#ef4444',
      borderUpColor: '#22c55e',
      borderDownColor: '#ef4444',
      wickUpColor: '#22c55e',
      wickDownColor: '#ef4444',
    })
    const candles: CandlestickData[] = data.bars.map((b) => ({
      time: b.time as unknown as import('lightweight-charts').Time,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }))
    candleSeries.setData(candles)

    // ── Volume series (own price scale, pinned to bottom 20%) ─────────────────
    const volumeSeries: ISeriesApi<'Histogram'> = chart.addHistogramSeries({
      priceScaleId: 'volume',
      priceFormat: { type: 'volume' },
      color: '#26a69a66',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })
    const volData: HistogramData[] = data.bars.map((b) => ({
      time: b.time as unknown as import('lightweight-charts').Time,
      value: b.volume,
      color: b.close >= b.open ? 'rgba(34,197,94,0.35)' : 'rgba(239,68,68,0.35)',
    }))
    volumeSeries.setData(volData)
    volumeRef.current = volumeSeries

    // ── EMA lines ─────────────────────────────────────────────────────────────
    const emaConfigs = [
      { key: 'ema_21' as const, color: '#3b82f6', ref: ema21Ref },
      { key: 'ema_50' as const, color: '#f97316', ref: ema50Ref },
      { key: 'ema_200' as const, color: '#6b7280', ref: ema200Ref },
    ]
    for (const { key, color, ref: seriesRef } of emaConfigs) {
      const pts = data.overlays[key]
      if (pts.length === 0) continue
      const s = chart.addLineSeries({
        color,
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      s.setData(
        pts.map((p) => ({
          time: p.time as unknown as import('lightweight-charts').Time,
          value: p.value,
        })),
      )
      seriesRef.current = s
    }

    // ── Supertrend line (per-point color) ─────────────────────────────────────
    const stPts = data.overlays.supertrend
    if (stPts.length > 0) {
      const stSeries = chart.addLineSeries({
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      })
      const stData: LineData[] = stPts.map((p) => ({
        time: p.time as unknown as import('lightweight-charts').Time,
        value: p.value,
        color: p.direction === 1 ? '#22c55e' : '#ef4444',
      }))
      stSeries.setData(stData)
      supertrendRef.current = stSeries
    }

    chart.timeScale().fitContent()

    // ── Canvas overlay for detection rectangles ───────────────────────────────
    // IMPORTANT: the canvas is created imperatively HERE, after createChart(),
    // so it is appended to the container AFTER LW's own canvases.  LW sets
    // z-index:1 (main canvas) and z-index:2 (crosshair canvas) on its elements.
    // By appending after them AND using z-index:3, our canvas paints on top.
    let overlayCanvas: HTMLCanvasElement | null = null
    if (detections !== undefined) {
      overlayCanvas = document.createElement('canvas')
      overlayCanvas.style.position = 'absolute'
      overlayCanvas.style.top = '0'
      overlayCanvas.style.left = '0'
      overlayCanvas.style.pointerEvents = 'none'
      overlayCanvas.style.zIndex = '3'
      container.appendChild(overlayCanvas)
      canvasRef.current = overlayCanvas

      const offset = Math.max(0, data.bars.length - YOLO_CHART_BARS)
      const timeToCoord = (time: string): number | null => {
        const coord = chart.timeScale().timeToCoordinate(time as unknown as Time)
        return coord ?? null
      }
      const priceToCoord = (price: number): number | null => {
        const coord = candleSeries.priceToCoordinate(price)
        return coord ?? null
      }

      const redraw = () => {
        const canvas = canvasRef.current
        if (!canvas) return
        const ctx = canvas.getContext('2d')
        if (!ctx) return
        canvas.width = container.clientWidth
        canvas.height = height
        drawDetectionOverlays(ctx, canvas.width, canvas.height, detections, offset, data.bars, timeToCoord, priceToCoord)
      }

      redraw()
      chart.timeScale().subscribeVisibleTimeRangeChange(redraw)
    }

    // ── Resize observer ────────────────────────────────────────────────────────
    const observer = new ResizeObserver(() => {
      if (container && chartRef.current) {
        chartRef.current.applyOptions({ width: container.clientWidth })
      }
    })
    observer.observe(container)

    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      ema21Ref.current = null
      ema50Ref.current = null
      ema200Ref.current = null
      supertrendRef.current = null
      volumeRef.current = null
      if (overlayCanvas && overlayCanvas.parentNode) {
        overlayCanvas.parentNode.removeChild(overlayCanvas)
      }
      canvasRef.current = null
    }
  }, [data, height, detections])

  // ── Apply overlay visibility changes without recreating the chart ──────────
  useEffect(() => {
    if (!overlays) return
    const applyVisible = <T extends 'Line' | 'Histogram'>(
      seriesRef: React.RefObject<ISeriesApi<T> | null>,
      visible: boolean,
    ) => {
      seriesRef.current?.applyOptions({ visible })
    }
    if (overlays.ema21 !== undefined) applyVisible(ema21Ref, overlays.ema21)
    if (overlays.ema50 !== undefined) applyVisible(ema50Ref, overlays.ema50)
    if (overlays.ema200 !== undefined) applyVisible(ema200Ref, overlays.ema200)
    if (overlays.supertrend !== undefined) applyVisible(supertrendRef, overlays.supertrend)
    if (overlays.volume !== undefined) applyVisible(volumeRef, overlays.volume)

    // Patterns visibility: show/hide canvas overlay
    if (overlays.patterns !== undefined && canvasRef.current) {
      canvasRef.current.style.display = overlays.patterns ? '' : 'none'
    }
  }, [overlays])

  return (
    <div
      ref={containerRef}
      style={{ position: 'relative', height }}
      className="rounded overflow-hidden"
    />
  )
})
