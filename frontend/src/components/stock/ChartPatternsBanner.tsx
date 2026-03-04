import type { ChartPatternDetection } from '../../types'

interface Props {
  patterns: ChartPatternDetection[]
  scannedAt: string | null
}

const DIRECTION_COLORS: Record<string, { border: string; bg: string; text: string; dot: string }> = {
  bullish: { border: 'border-green-700/50', bg: 'bg-green-950/40', text: 'text-green-400', dot: 'text-green-400' },
  bearish: { border: 'border-red-700/50', bg: 'bg-red-950/40', text: 'text-red-400', dot: 'text-red-400' },
  neutral: { border: 'border-gray-700/50', bg: 'bg-gray-900/40', text: 'text-gray-400', dot: 'text-gray-500' },
}

function formatPatternName(name: string): string {
  return name
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function formatTimeAgo(iso: string): string {
  const secs = Math.round((Date.now() - new Date(iso).getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`
  return `${Math.floor(secs / 86400)}d ago`
}

export function ChartPatternsBanner({ patterns, scannedAt }: Props) {
  if (patterns.length === 0 && !scannedAt) {
    return (
      <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 px-4 py-3">
        <div className="flex items-center justify-between text-sm">
          <span className="text-gray-500 font-medium">Chart Patterns (YOLOv8)</span>
          <span className="text-gray-600 text-xs">Not scanned yet</span>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 px-4 py-3">
      <div className="flex items-center justify-between mb-2">
        <span className="text-gray-400 font-medium text-sm">Chart Patterns (YOLOv8)</span>
        {scannedAt && (
          <span className="text-gray-600 text-xs">
            Scanned: {formatTimeAgo(scannedAt)}
          </span>
        )}
      </div>
      {patterns.length === 0 ? (
        <p className="text-gray-600 text-xs">No patterns detected</p>
      ) : (
        <div className="flex flex-wrap gap-2">
          {patterns.map((det) => {
            const colors = DIRECTION_COLORS[det.direction] ?? DIRECTION_COLORS.neutral
            const confPct = Math.round(det.confidence * 100)
            return (
              <div
                key={`${det.pattern}-${det.bar_start}`}
                className={`rounded border ${colors.border} ${colors.bg} px-3 py-1.5 text-sm flex items-center gap-2`}
              >
                <span className={colors.dot}>●</span>
                <span className={`font-semibold ${colors.text}`}>
                  {formatPatternName(det.pattern)}
                </span>
                <span className="text-gray-400 font-mono text-xs">{confPct}%</span>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
