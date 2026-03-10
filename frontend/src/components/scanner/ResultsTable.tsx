import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ForecastData, ScannerResult, SynthesisData } from '../../types'
import { ProfileBadge } from './ProfileBadge'
import { RowExpansion } from './RowExpansion'
import { ScoreDisplay, scoreColor } from '../shared/ScoreDisplay'

const PROFILE_LABELS: Record<string, string> = {
  MomentumBreakout: 'Momentum Breakout',
  MeanReversion: 'Mean Reversion',
  TrendFollowing: 'Trend Following',
  HarmonicSetup: 'Harmonic Setup',
}

interface Props {
  results: ScannerResult[]
  activeProfile?: string | null
  hasScanned?: boolean
  forecasts?: Record<string, ForecastData>
  syntheses?: Record<string, SynthesisData>
}

export function ResultsTable({ results, activeProfile, hasScanned, forecasts, syntheses }: Props) {
  const navigate = useNavigate()
  const [expanded, setExpanded] = useState<Set<string>>(new Set())

  function toggleExpand(symbol: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(symbol)) next.delete(symbol)
      else next.add(symbol)
      return next
    })
  }

  if (results.length === 0) {
    // Contextual empty state: distinguish "never scanned" vs "no matches for this filter"
    if (hasScanned && activeProfile) {
      const label = PROFILE_LABELS[activeProfile] ?? activeProfile
      return (
        <div className="text-center py-16 text-gray-500">
          <p className="text-lg">No stocks match <span className="text-gray-300">{label}</span></p>
          <p className="text-sm mt-1">None of your watchlist symbols currently meet this profile's criteria. Check the <span className="text-gray-300">All</span> tab for full results.</p>
        </div>
      )
    }
    return (
      <div className="text-center py-16 text-gray-500">
        <p className="text-lg">No results yet</p>
        <p className="text-sm mt-1">Click <span className="text-gray-300">Run Scan</span> to analyze your watchlist.</p>
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-gray-700/50">
      <table className="w-full text-sm border-collapse">
        <thead>
          <tr className="bg-gray-800/80 text-gray-400 text-xs uppercase tracking-wider">
            <th className="px-3 py-2 text-right w-12">#</th>
            <th className="px-3 py-2 text-left">Symbol</th>
            <th className="px-3 py-2 text-right">Score</th>
            <th className="px-3 py-2 text-right">Price</th>
            <th className="px-3 py-2 text-right">Chg%</th>
            <th className="px-3 py-2 text-right">ATR%</th>
            <th className="px-3 py-2 text-left">Profiles</th>
            <th className="px-3 py-2 text-left">Setup</th>
            <th className="px-3 py-2 text-left">Patterns</th>
            <th className="px-3 py-2 text-left">EW</th>
            <th className="px-3 py-2 text-right">Forecast</th>
            <th className="px-3 py-2 w-10" />
          </tr>
        </thead>
        <tbody>
          {results.map((r) => {
            const isExpanded = expanded.has(r.symbol)
            const chgPct = r.meta.price_change_pct
            const chgColor = chgPct > 0 ? 'text-green-400' : chgPct < 0 ? 'text-red-400' : 'text-gray-400'

            return (
              <>
                <tr
                  key={r.symbol}
                  className="border-t border-gray-700/40 hover:bg-gray-800/40 cursor-pointer transition-colors"
                  onClick={() => navigate(`/stock/${r.symbol}`)}
                >
                  <td className="px-3 py-2.5 text-right text-gray-500 font-mono text-xs">{r.rank}</td>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-1.5">
                      <span className="font-semibold text-white font-mono">{r.symbol}</span>
                      {r.is_actionable && (
                        <span className="text-xs text-blue-400" title="Actionable: ≥3 categories agree">●</span>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-right" onClick={(e) => e.stopPropagation()}>
                    <ScoreDisplay score={r.composite_score} showBar />
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-gray-200">
                    ${r.meta.last_price.toFixed(2)}
                  </td>
                  <td className={`px-3 py-2.5 text-right font-mono ${chgColor}`}>
                    {chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%
                  </td>
                  <td className="px-3 py-2.5 text-right font-mono text-gray-400">
                    {r.meta.atr_pct.toFixed(2)}%
                  </td>
                  <td className="px-3 py-2.5">
                    <div className="flex flex-wrap gap-1">
                      {r.profile_matches.length === 0 ? (
                        <span className="text-gray-600 text-xs">—</span>
                      ) : (
                        r.profile_matches.map((p) => <ProfileBadge key={p} profile={p} />)
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    {(() => {
                      const syn = syntheses?.[r.symbol]
                      if (!syn) return <span className="text-gray-600 text-xs">—</span>
                      const biasColors: Record<string, string> = {
                        bullish: 'text-green-400',
                        bearish: 'text-red-400',
                        neutral: 'text-gray-400',
                      }
                      const confBadgeStyles: Record<string, { bg: string; text: string; label: string }> = {
                        high: { bg: 'bg-green-900/50', text: 'text-green-300', label: 'H' },
                        medium: { bg: 'bg-yellow-900/50', text: 'text-yellow-300', label: 'M' },
                        low: { bg: 'bg-gray-800/50', text: 'text-gray-400', label: 'L' },
                      }
                      const confStyle = confBadgeStyles[syn.confidence]
                      return (
                        <div className="flex items-center gap-2">
                          <span className={`${biasColors[syn.bias]}`}>●</span>
                          <span className="text-xs font-medium text-gray-300">{syn.setup_type}</span>
                          <span className={`${confStyle.bg} ${confStyle.text} rounded px-1 py-0.5 text-xs font-semibold`}>
                            {confStyle.label}
                          </span>
                        </div>
                      )
                    })()}
                  </td>
                  <td className="px-3 py-2.5">
                    {(() => {
                      const best = r.chart_patterns?.[0]
                      if (!best) return <span className="text-gray-600 text-xs">—</span>
                      const dirColor = best.direction === 'bullish'
                        ? 'text-green-400'
                        : best.direction === 'bearish'
                          ? 'text-red-400'
                          : 'text-gray-400'
                      const label = best.pattern
                        .split('_')
                        .map((w: string) => w.charAt(0).toUpperCase() + w.slice(1))
                        .join(' ')
                      return (
                        <span className={`text-xs font-medium ${dirColor}`}>
                          {best.direction === 'bullish' ? '▲' : best.direction === 'bearish' ? '▼' : '◆'}{' '}
                          {label} {Math.round(best.confidence * 100)}%
                        </span>
                      )
                    })()}
                  </td>
                  <td className="px-3 py-2.5">
                    {(() => {
                      const sigs = r.signals ?? {}
                      const w3 = sigs.ew_wave3_active ?? 0
                      const w5 = sigs.ew_wave5_active ?? 0
                      const abc = sigs.ew_corrective_abc ?? 0
                      const quality = sigs.ew_ratio_quality ?? 0

                      if (quality < 0.1) return <span className="text-gray-600 text-xs">—</span>

                      let label = ''
                      let colorClass = 'text-gray-400'
                      if (w3 > 0.5) { label = 'W3 ↑'; colorClass = 'text-green-400' }
                      else if (w5 > 0.3) { label = 'W5 ↑'; colorClass = 'text-green-300' }
                      else if (abc < -0.1) { label = 'ABC ↓'; colorClass = 'text-red-400' }
                      else { label = `EW ${Math.round(quality * 100)}%`; colorClass = 'text-gray-400' }

                      return (
                        <span
                          className={`text-xs font-medium ${colorClass}`}
                          title={`EW quality: ${Math.round(quality * 100)}%`}
                        >
                          {label}
                        </span>
                      )
                    })()}
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    {(() => {
                      const fc = forecasts?.[r.symbol]
                      if (!fc || fc.direction_confidence < 0.6) {
                        return <span className="text-gray-600 text-xs">—</span>
                      }
                      const colorClass = fc.direction === 'bullish'
                        ? 'text-green-400'
                        : fc.direction === 'bearish'
                          ? 'text-red-400'
                          : 'text-gray-400'
                      const arrow = fc.direction === 'bullish' ? '▲' : fc.direction === 'bearish' ? '▼' : '◆'
                      const sign = fc.expected_move_pct >= 0 ? '+' : ''
                      return (
                        <span className={`text-xs font-medium ${colorClass}`}>
                          {arrow} {sign}{fc.expected_move_pct.toFixed(1)}%
                        </span>
                      )
                    })()}
                  </td>
                  <td
                    className="px-3 py-2.5 text-center text-gray-500 hover:text-gray-200"
                    onClick={(e) => { e.stopPropagation(); toggleExpand(r.symbol) }}
                  >
                    <span className="text-xs select-none">{isExpanded ? '▾' : '▸'}</span>
                  </td>
                </tr>
                {isExpanded && (
                  <tr key={`${r.symbol}-expand`} className="border-t border-gray-700/30">
                    <td colSpan={12} className="p-0">
                      <RowExpansion categoryScores={r.category_scores} />
                    </td>
                  </tr>
                )}
              </>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// Re-export for use in pages
export { scoreColor }
