import { useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import { createChart, type IChartApi, type ISeriesApi, type HistogramData, type LineData, type CandlestickData, type Time } from 'lightweight-charts'
import type { ChartPatternDetection, OHLCVBar, OHLCVResponse, EWWavePoint, ForecastData } from '../../types'
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
  ewWaves?: EWWavePoint[] | null
  ewDirection?: 'bullish' | 'bearish' | null
  forecastData?: ForecastData | null
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

  // Resolve coordinates — skip if any point is unresolvable
  const coords: Array<{ x: number; y: number; label: string }> = []
  for (const w of waves) {
    const x = timeToCoordinate(w.time)
    const y = priceToCoordinate(w.price)
    if (x === null || y === null) return   // bail on first unresolvable point
    coords.push({ x, y, label: w.label })
  }

  const color = direction === 'bullish'
    ? 'rgba(34, 197, 94, 0.9)'
    : direction === 'bearish'
      ? 'rgba(239, 68, 68, 0.9)'
      : 'rgba(150, 150, 150, 0.9)'

  // Draw polyline
  ctx.strokeStyle = color
  ctx.lineWidth = 1.5
  ctx.beginPath()
  ctx.moveTo(coords[0].x, coords[0].y)
  for (let i = 1; i < coords.length; i++) {
    ctx.lineTo(coords[i].x, coords[i].y)
  }
  ctx.stroke()

  // Draw labels at each pivot
  ctx.font = '10px sans-serif'
  ctx.fillStyle = color
  for (const pt of coords) {
    ctx.beginPath()
    ctx.arc(pt.x, pt.y, 4, 0, Math.PI * 2)
    ctx.fill()
    ctx.fillText(pt.label, pt.x + 5, pt.y - 5)
  }
}

export function drawForecastOverlay(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  forecast: ForecastData,
  lastBarTime: string,
  timeToCoordinate: (time: string) => number | null,
  priceToCoordinate: (price: number) => number | null,
  bars: OHLCVBar[],
): void {
  ctx.clearRect(0, 0, width, height)

  const { median, quantile_10, quantile_90, quantile_25, quantile_75 } = forecast.forecast
  const horizon = median.length

  // We need pixel positions — estimate bar spacing from the last two bars
  const lastBarX = timeToCoordinate(lastBarTime)
  if (lastBarX === null) return

  let barSpacing = 8
  if (bars.length >= 2) {
    const secondLastX = timeToCoordinate(bars[bars.length - 2].time)
    if (secondLastX !== null) {
      barSpacing = Math.abs(lastBarX - secondLastX)
    }
  }

  // Build coords for each horizon step
  const coords: Array<{
    x: number
    med: number | null
    q10: number | null
    q90: number | null
    q25: number | null
    q75: number | null
  }> = []
  for (let i = 0; i < horizon; i++) {
    const x = lastBarX + (i + 1) * barSpacing
    coords.push({
      x,
      med: priceToCoordinate(median[i]),
      q10: priceToCoordinate(quantile_10[i]),
      q90: priceToCoordinate(quantile_90[i]),
      q25: priceToCoordinate(quantile_25[i]),
      q75: priceToCoordinate(quantile_75[i]),
    })
  }

  const isBullish = forecast.direction === 'bullish'
  const isBearish = forecast.direction === 'bearish'
  const baseColor = isBullish ? '34, 197, 94' : isBearish ? '239, 68, 68' : '156, 163, 175'

  // Outer band (q10–q90), 0.08 alpha
  ctx.fillStyle = `rgba(${baseColor}, 0.08)`
  ctx.beginPath()
  for (let i = 0; i < coords.length; i++) {
    const c = coords[i]
    if (c.q90 === null) continue
    if (i === 0) ctx.moveTo(c.x, c.q90)
    else ctx.lineTo(c.x, c.q90)
  }
  for (let i = coords.length - 1; i >= 0; i--) {
    const c = coords[i]
    if (c.q10 === null) continue
    ctx.lineTo(c.x, c.q10)
  }
  ctx.closePath()
  ctx.fill()

  // Inner band (q25–q75), 0.15 alpha
  ctx.fillStyle = `rgba(${baseColor}, 0.15)`
  ctx.beginPath()
  for (let i = 0; i < coords.length; i++) {
    const c = coords[i]
    if (c.q75 === null) continue
    if (i === 0) ctx.moveTo(c.x, c.q75)
    else ctx.lineTo(c.x, c.q75)
  }
  for (let i = coords.length - 1; i >= 0; i--) {
    const c = coords[i]
    if (c.q25 === null) continue
    ctx.lineTo(c.x, c.q25)
  }
  ctx.closePath()
  ctx.fill()

  // Median dashed line
  ctx.strokeStyle = `rgba(${baseColor}, 0.7)`
  ctx.lineWidth = 1.5
  ctx.setLineDash([4, 3])
  ctx.beginPath()
  let started = false
  for (const c of coords) {
    if (c.med === null) continue
    if (!started) { ctx.moveTo(c.x, c.med); started = true }
    else ctx.lineTo(c.x, c.med)
  }
  ctx.stroke()
  ctx.setLineDash([])

  // Label at end
  const lastCoord = coords[coords.length - 1]
  if (lastCoord.med !== null) {
    const moveSign = forecast.expected_move_pct >= 0 ? '+' : ''
    const label = `${moveSign}${forecast.expected_move_pct.toFixed(1)}% (${forecast.horizon_bars}d)`
    ctx.font = '10px sans-serif'
    ctx.fillStyle = `rgba(${baseColor}, 0.9)`
    ctx.fillText(label, lastCoord.x + 4, lastCoord.med - 4)
  }
}

// ── Component ─────────────────────────────────────────────────────────────────

export const CandlestickChart = forwardRef<ChartHandle, Props>(function CandlestickChart(
  { data, height = 420, detections, overlays, ewWaves, ewDirection, forecastData },
  ref,
) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  // canvasRef is populated imperatively in useEffect AFTER createChart so it sits
  // above LW's own canvases in DOM order (z-index: 1 and z-index: 2).
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const ewCanvasRef = useRef<HTMLCanvasElement | null>(null)

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

    // ── Shared coordinate helpers (used by both canvas overlays) ─────────────
    const timeToCoord = (time: string): number | null => {
      const coord = chart.timeScale().timeToCoordinate(time as unknown as Time)
      return coord ?? null
    }
    const priceToCoord = (price: number): number | null => {
      const coord = candleSeries.priceToCoordinate(price)
      return coord ?? null
    }

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

    // ── EW wave canvas overlay (z-index: 4) ──────────────────────────────────
    let ewCanvas: HTMLCanvasElement | null = null
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

    // ── Forecast canvas overlay (z-index: 5) ──────────────────────────────
    let forecastCanvas: HTMLCanvasElement | null = null
    if (forecastData) {
      forecastCanvas = document.createElement('canvas')
      forecastCanvas.style.position = 'absolute'
      forecastCanvas.style.top = '0'
      forecastCanvas.style.left = '0'
      forecastCanvas.style.pointerEvents = 'none'
      forecastCanvas.style.zIndex = '5'
      container.appendChild(forecastCanvas)

      const redrawForecast = () => {
        if (!forecastCanvas) return
        const fctx = forecastCanvas.getContext('2d')
        if (!fctx) return
        forecastCanvas.width = container.clientWidth
        forecastCanvas.height = height
        drawForecastOverlay(
          fctx, forecastCanvas.width, forecastCanvas.height,
          forecastData, data.bars[data.bars.length - 1].time,
          timeToCoord, priceToCoord, data.bars,
        )
      }
      redrawForecast()
      chart.timeScale().subscribeVisibleTimeRangeChange(redrawForecast)
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
      if (ewCanvas && ewCanvas.parentNode) {
        ewCanvas.parentNode.removeChild(ewCanvas)
      }
      ewCanvasRef.current = null
      if (forecastCanvas && forecastCanvas.parentNode) {
        forecastCanvas.parentNode.removeChild(forecastCanvas)
      }
    }
  }, [data, height, detections, ewWaves, ewDirection, forecastData])

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

    // Waves visibility: show/hide EW canvas overlay
    if (overlays.waves !== undefined && ewCanvasRef.current) {
      ewCanvasRef.current.style.display = overlays.waves ? '' : 'none'
    }

    // Forecast visibility
    if (overlays.forecast !== undefined) {
      const el = containerRef.current
      if (el) {
        const fcCanvas = el.querySelector<HTMLCanvasElement>('canvas[style*="z-index: 5"]')
        if (fcCanvas) {
          fcCanvas.style.display = overlays.forecast ? '' : 'none'
        }
      }
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
