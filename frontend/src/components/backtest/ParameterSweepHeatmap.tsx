import { useEffect, useRef, useCallback } from 'react'
import type { SweepResponse } from '../../types'

interface Props {
  sweepResult: SweepResponse
  onSelectCell: (index: number) => void
}

interface ParsedHeatmapData {
  xValues: number[]
  yValues: number[]
  grid: number[][]
  xLabel: string
  yLabel: string
}

function parseHeatmapData(rawData: Record<string, number>): ParsedHeatmapData {
  // Keys are stringified tuples like "(9, 26)" or similar
  const entries: Array<{ x: number; y: number; value: number }> = []

  for (const [key, value] of Object.entries(rawData)) {
    const match = key.match(/\(([\d.]+),\s*([\d.]+)\)/)
    if (match) {
      entries.push({
        x: parseFloat(match[1]),
        y: parseFloat(match[2]),
        value,
      })
    }
  }

  if (entries.length === 0) {
    return { xValues: [], yValues: [], grid: [], xLabel: 'X', yLabel: 'Y' }
  }

  const xSet = new Set(entries.map((e) => e.x))
  const ySet = new Set(entries.map((e) => e.y))
  const xValues = Array.from(xSet).sort((a, b) => a - b)
  const yValues = Array.from(ySet).sort((a, b) => a - b)

  // Build grid (y rows × x cols)
  const grid: number[][] = Array(yValues.length)
    .fill(null)
    .map(() => Array(xValues.length).fill(0))

  for (const entry of entries) {
    const xi = xValues.indexOf(entry.x)
    const yi = yValues.indexOf(entry.y)
    if (xi >= 0 && yi >= 0) {
      grid[yi][xi] = entry.value
    }
  }

  // Label guess based on common parameter patterns
  const xLabel = xValues.length > 1 ? 'Param 1' : 'X'
  const yLabel = yValues.length > 1 ? 'Param 2' : 'Y'

  return { xValues, yValues, grid, xLabel, yLabel }
}

function getColor(value: number, minVal: number, maxVal: number): string {
  const range = maxVal - minVal
  const normalized = (value - minVal) / (range || 1)

  // Red → Yellow → Green gradient
  let r, g, b
  if (normalized < 0.5) {
    // Red → Yellow
    const t = normalized * 2
    r = 255
    g = Math.round(255 * t)
    b = 0
  } else {
    // Yellow → Green
    const t = (normalized - 0.5) * 2
    r = Math.round(255 * (1 - t))
    g = 255
    b = 0
  }

  return `rgba(${r}, ${g}, ${b}, 0.8)`
}

export function ParameterSweepHeatmap({ sweepResult, onSelectCell }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const parsed = parseHeatmapData(sweepResult.heatmap_data)

  const handleCanvasClick = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      if (!containerRef.current || parsed.grid.length === 0) return

      const rect = canvasRef.current!.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top

      const padding = 60
      const cellWidth = (rect.width - padding * 1.5) / parsed.xValues.length
      const cellHeight = (rect.height - padding * 1.5) / parsed.yValues.length

      const col = Math.floor((x - padding) / cellWidth)
      const row = Math.floor((y - padding) / cellHeight)

      if (col >= 0 && col < parsed.xValues.length && row >= 0 && row < parsed.yValues.length) {
        // Find the index in the original results that matches this cell
        const value = parsed.grid[row][col]
        const resultIdx = sweepResult.results.findIndex((r) => r.stats.total_return_pct === value)
        if (resultIdx >= 0) {
          onSelectCell(resultIdx)
        }
      }
    },
    [parsed, sweepResult, onSelectCell]
  )

  useEffect(() => {
    const canvas = canvasRef.current
    const container = containerRef.current
    if (!canvas || !container || parsed.grid.length === 0) return

    const ctx = canvas.getContext('2d')
    if (!ctx) return

    const width = container.clientWidth
    const height = 400

    canvas.width = width
    canvas.height = height

    const padding = 60
    const availWidth = width - padding * 1.5
    const availHeight = height - padding * 1.5
    const cellWidth = availWidth / parsed.xValues.length
    const cellHeight = availHeight / parsed.yValues.length

    // Background
    ctx.fillStyle = '#0d1117'
    ctx.fillRect(0, 0, width, height)

    // Find min/max for color scaling
    const allValues = parsed.grid.flat().filter((v) => v !== 0)
    const minVal = Math.min(...allValues)
    const maxVal = Math.max(...allValues)

    // Draw grid
    for (let row = 0; row < parsed.grid.length; row++) {
      for (let col = 0; col < parsed.grid[row].length; col++) {
        const x = padding + col * cellWidth
        const y = padding + row * cellHeight
        const value = parsed.grid[row][col]

        ctx.fillStyle = getColor(value, minVal, maxVal)
        ctx.fillRect(x, y, cellWidth, cellHeight)

        ctx.strokeStyle = 'rgba(60, 60, 60, 0.5)'
        ctx.lineWidth = 1
        ctx.strokeRect(x, y, cellWidth, cellHeight)

        // Value label
        ctx.fillStyle = '#8b949e'
        ctx.font = '10px sans-serif'
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText(value.toFixed(1), x + cellWidth / 2, y + cellHeight / 2)
      }
    }

    // X axis labels
    ctx.fillStyle = '#8b949e'
    ctx.font = '11px sans-serif'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'top'
    for (let i = 0; i < parsed.xValues.length; i++) {
      const x = padding + (i + 0.5) * cellWidth
      ctx.fillText(String(parsed.xValues[i]), x, height - 40)
    }

    // X axis label
    ctx.fillStyle = '#6b7280'
    ctx.font = 'bold 12px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(parsed.xLabel, width / 2, height - 15)

    // Y axis labels
    ctx.fillStyle = '#8b949e'
    ctx.font = '11px sans-serif'
    ctx.textAlign = 'right'
    ctx.textBaseline = 'middle'
    for (let i = 0; i < parsed.yValues.length; i++) {
      const y = padding + (i + 0.5) * cellHeight
      ctx.fillText(String(parsed.yValues[i]), padding - 10, y)
    }

    // Y axis label
    ctx.save()
    ctx.translate(15, height / 2)
    ctx.rotate(-Math.PI / 2)
    ctx.fillStyle = '#6b7280'
    ctx.font = 'bold 12px sans-serif'
    ctx.textAlign = 'center'
    ctx.fillText(parsed.yLabel, 0, 0)
    ctx.restore()
  }, [parsed])

  if (parsed.grid.length === 0) {
    return <div className="text-center py-8 text-gray-500">No heatmap data</div>
  }

  return (
    <div ref={containerRef} className="rounded border border-gray-800 bg-gray-900/50 p-4">
      <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3">
        Parameter Sweep Results
      </div>
      <canvas
        ref={canvasRef}
        onClick={handleCanvasClick}
        style={{ cursor: 'pointer', width: '100%', height: 'auto' }}
        className="rounded"
      />
      <div className="text-xs text-gray-500 mt-3">
        Click on a cell to view that result's details
      </div>
    </div>
  )
}
