import { type CategoryScores as CategoryScoresType } from '../../types'
import { scoreColor } from '../shared/ScoreDisplay'

const CATEGORIES: { key: keyof CategoryScoresType; label: string; weight: string }[] = [
  { key: 'trend', label: 'Trend', weight: '30%' },
  { key: 'momentum', label: 'Momentum', weight: '20%' },
  { key: 'volume', label: 'Volume', weight: '15%' },
  { key: 'volatility', label: 'Volatility', weight: '10%' },
  { key: 'support_resistance', label: 'S/R', weight: '10%' },
  { key: 'divergence', label: 'Divergence', weight: '10%' },
  { key: 'pattern', label: 'Patterns', weight: '5%' },
]

interface Props {
  scores: CategoryScoresType
  onSelect?: (category: keyof CategoryScoresType | null) => void
  selected?: keyof CategoryScoresType | null
}

export function CategoryScoresPanel({ scores, onSelect, selected }: Props) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-3">
        Category Scores
      </h3>
      {CATEGORIES.map(({ key, label, weight }) => {
        const score = scores[key]
        const magnitude = Math.min(1, Math.abs(score))
        const pct = `${Math.round(magnitude * 100)}%`
        const barColor = score >= 0.1 ? 'bg-green-500' : score <= -0.1 ? 'bg-red-500' : 'bg-gray-500'
        const isActive = selected === key

        return (
          <button
            key={key}
            className={`w-full text-left rounded px-2 py-1.5 transition-colors ${
              isActive ? 'bg-gray-700' : 'hover:bg-gray-800/60'
            }`}
            onClick={() => onSelect?.(isActive ? null : key)}
          >
            <div className="flex items-center gap-2">
              <span className="text-xs text-gray-300 w-24 shrink-0">{label}</span>
              <div className="flex-1 h-1.5 bg-gray-700 rounded overflow-hidden">
                <div
                  className={`h-full ${barColor} rounded`}
                  style={{ width: pct }}
                />
              </div>
              <span className={`text-xs font-mono w-12 text-right ${scoreColor(score)}`}>
                {score.toFixed(3)}
              </span>
              <span className="text-xs text-gray-600 w-8 text-right">{weight}</span>
            </div>
          </button>
        )
      })}
    </div>
  )
}
