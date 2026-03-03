import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { ScannerResult } from '../../types'
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
}

export function ResultsTable({ results, activeProfile, hasScanned }: Props) {
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
                  <td
                    className="px-3 py-2.5 text-center text-gray-500 hover:text-gray-200"
                    onClick={(e) => { e.stopPropagation(); toggleExpand(r.symbol) }}
                  >
                    <span className="text-xs select-none">{isExpanded ? '▾' : '▸'}</span>
                  </td>
                </tr>
                {isExpanded && (
                  <tr key={`${r.symbol}-expand`} className="border-t border-gray-700/30">
                    <td colSpan={8} className="p-0">
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
