import { useState, useMemo } from 'react'
import type { BacktestTrade } from '../../types'

interface Props {
  trades: BacktestTrade[]
}

type SortField = 'entry_date' | 'exit_date' | 'entry_price' | 'exit_price' | 'pnl_pct' | 'pnl_abs' | 'duration'
type SortDirection = 'asc' | 'desc'

const TRADES_PER_PAGE = 20

function getDurationDays(entryDate: string, exitDate: string): number {
  const entry = new Date(entryDate)
  const exit = new Date(exitDate)
  return Math.ceil((exit.getTime() - entry.getTime()) / (1000 * 60 * 60 * 24))
}

export function TradeListTable({ trades }: Props) {
  const [sortField, setSortField] = useState<SortField>('entry_date')
  const [sortDirection, setSortDirection] = useState<SortDirection>('asc')
  const [currentPage, setCurrentPage] = useState(0)

  const sorted = useMemo(() => {
    const copy = [...trades]
    copy.sort((a, b) => {
      let aVal: string | number
      let bVal: string | number

      if (sortField === 'duration') {
        aVal = getDurationDays(a.entry_date, a.exit_date)
        bVal = getDurationDays(b.entry_date, b.exit_date)
      } else {
        aVal = a[sortField as keyof BacktestTrade]
        bVal = b[sortField as keyof BacktestTrade]
      }

      if (typeof aVal === 'string') aVal = aVal.localeCompare(bVal as string)
      else aVal = (aVal as number) - (bVal as number)

      return sortDirection === 'asc' ? aVal : -aVal
    })
    return copy
  }, [trades, sortField, sortDirection])

  const paged = sorted.slice(currentPage * TRADES_PER_PAGE, (currentPage + 1) * TRADES_PER_PAGE)
  const totalPages = Math.ceil(trades.length / TRADES_PER_PAGE)

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection(sortDirection === 'asc' ? 'desc' : 'asc')
    } else {
      setSortField(field)
      setSortDirection('asc')
    }
    setCurrentPage(0)
  }

  const SortIcon = ({ field }: { field: SortField }) => {
    if (sortField !== field) return <span className="text-gray-700">↕</span>
    return <span className="text-blue-400">{sortDirection === 'asc' ? '↑' : '↓'}</span>
  }

  if (trades.length === 0) {
    return <div className="text-center py-8 text-gray-500">No trades</div>
  }

  return (
    <div className="space-y-4">
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left px-3 py-2 font-semibold text-gray-400 cursor-pointer hover:text-gray-200" onClick={() => handleSort('entry_date')}>
                Date In <SortIcon field="entry_date" />
              </th>
              <th className="text-left px-3 py-2 font-semibold text-gray-400 cursor-pointer hover:text-gray-200" onClick={() => handleSort('exit_date')}>
                Date Out <SortIcon field="exit_date" />
              </th>
              <th className="text-right px-3 py-2 font-semibold text-gray-400 cursor-pointer hover:text-gray-200" onClick={() => handleSort('entry_price')}>
                Entry <SortIcon field="entry_price" />
              </th>
              <th className="text-right px-3 py-2 font-semibold text-gray-400 cursor-pointer hover:text-gray-200" onClick={() => handleSort('exit_price')}>
                Exit <SortIcon field="exit_price" />
              </th>
              <th className="text-right px-3 py-2 font-semibold text-gray-400 cursor-pointer hover:text-gray-200" onClick={() => handleSort('pnl_pct')}>
                P&L % <SortIcon field="pnl_pct" />
              </th>
              <th className="text-right px-3 py-2 font-semibold text-gray-400 cursor-pointer hover:text-gray-200" onClick={() => handleSort('pnl_abs')}>
                P&L $ <SortIcon field="pnl_abs" />
              </th>
              <th className="text-right px-3 py-2 font-semibold text-gray-400 cursor-pointer hover:text-gray-200" onClick={() => handleSort('duration')}>
                Days <SortIcon field="duration" />
              </th>
            </tr>
          </thead>
          <tbody>
            {paged.map((trade, idx) => {
              const pnlColor = trade.pnl_pct >= 0 ? 'text-green-400' : 'text-red-400'
              const durationDays = getDurationDays(trade.entry_date, trade.exit_date)
              return (
                <tr key={idx} className="border-b border-gray-900 hover:bg-gray-900/30">
                  <td className="px-3 py-2 text-gray-400">{trade.entry_date.substring(0, 10)}</td>
                  <td className="px-3 py-2 text-gray-400">{trade.exit_date.substring(0, 10)}</td>
                  <td className="px-3 py-2 text-right text-gray-300 font-mono">${trade.entry_price.toFixed(2)}</td>
                  <td className="px-3 py-2 text-right text-gray-300 font-mono">${trade.exit_price.toFixed(2)}</td>
                  <td className={`px-3 py-2 text-right font-mono font-semibold ${pnlColor}`}>
                    {trade.pnl_pct.toFixed(2)}%
                  </td>
                  <td className={`px-3 py-2 text-right font-mono font-semibold ${pnlColor}`}>
                    ${trade.pnl_abs.toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right text-gray-400">{durationDays}d</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between text-xs text-gray-400">
        <div>
          {trades.length > 0 && (
            <span>
              Showing {currentPage * TRADES_PER_PAGE + 1}-{Math.min((currentPage + 1) * TRADES_PER_PAGE, trades.length)} of {trades.length} trades
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setCurrentPage(Math.max(0, currentPage - 1))}
            disabled={currentPage === 0}
            className="px-2 py-1 rounded border border-gray-700 hover:border-gray-500 disabled:opacity-50 transition-colors"
          >
            Previous
          </button>
          <span className="px-2 py-1 text-gray-500">
            Page {currentPage + 1} of {totalPages}
          </span>
          <button
            onClick={() => setCurrentPage(Math.min(totalPages - 1, currentPage + 1))}
            disabled={currentPage >= totalPages - 1}
            className="px-2 py-1 rounded border border-gray-700 hover:border-gray-500 disabled:opacity-50 transition-colors"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  )
}
