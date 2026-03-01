import type { CategoryScores } from '../../types'
import { scoreColor } from '../shared/ScoreDisplay'

const CATEGORY_LABELS: Record<keyof CategoryScores, string> = {
  trend: 'Trend',
  momentum: 'Momentum',
  volume: 'Volume',
  volatility: 'Volatility',
  support_resistance: 'S/R',
  divergence: 'Divergence',
  pattern: 'Patterns',
}

interface Props {
  categoryScores: CategoryScores
}

export function RowExpansion({ categoryScores }: Props) {
  const entries = Object.entries(CATEGORY_LABELS) as [keyof CategoryScores, string][]

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-x-6 gap-y-2 px-4 py-3 bg-gray-900/60 border-t border-gray-700/50">
      {entries.map(([key, label]) => {
        const score = categoryScores[key]
        const magnitude = Math.min(1, Math.abs(score))
        const pct = `${Math.round(magnitude * 100)}%`
        const isPos = score >= 0
        const barColor = score >= 0.1 ? 'bg-green-500' : score <= -0.1 ? 'bg-red-500' : 'bg-gray-500'

        return (
          <div key={key} className="flex items-center gap-2 min-w-0">
            <span className="text-xs text-gray-400 w-20 shrink-0">{label}</span>
            {/* Progress bar */}
            <div className="flex-1 h-1.5 bg-gray-700 rounded overflow-hidden flex">
              {isPos ? (
                <div className={`h-full ${barColor} rounded`} style={{ width: pct }} />
              ) : (
                <>
                  <div className="flex-1" />
                  <div className={`h-full ${barColor} rounded`} style={{ width: pct }} />
                </>
              )}
            </div>
            <span className={`text-xs font-mono w-10 text-right ${scoreColor(score)}`}>
              {score.toFixed(2)}
            </span>
          </div>
        )
      })}
    </div>
  )
}
