import { useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { scannerApi } from '../api/scanner'
import { useStockStore } from '../stores/stockStore'
import { CandlestickChart } from '../components/stock/CandlestickChart'
import { CategoryScoresPanel } from '../components/stock/CategoryScores'
import { SignalsPanel } from '../components/stock/SignalsPanel'
import { HarmonicBanner } from '../components/stock/HarmonicBanner'
import { ChartPatternsBanner } from '../components/stock/ChartPatternsBanner'
import { ProfileBadge } from '../components/scanner/ProfileBadge'
import { LoadingSpinner } from '../components/shared/LoadingSpinner'
import { ScoreDisplay } from '../components/shared/ScoreDisplay'
import type { CategoryScores } from '../types'

export function StockDetailPage() {
  const { symbol = '' } = useParams<{ symbol: string }>()
  const navigate = useNavigate()
  const { chartTimeframe, setChartTimeframe } = useStockStore()
  const [selectedCategory, setSelectedCategory] = useState<keyof CategoryScores | null>(null)

  const { data: detail, isLoading: detailLoading, isError: detailError } = useQuery({
    queryKey: ['scanner', 'detail', symbol, chartTimeframe],
    queryFn: () => scannerApi.getDetail(symbol, chartTimeframe),
    enabled: !!symbol,
    staleTime: 60_000,
  })

  const { data: ohlcv, isLoading: chartLoading } = useQuery({
    queryKey: ['stocks', symbol, 'ohlcv', chartTimeframe],
    queryFn: () => scannerApi.getOHLCV(symbol, chartTimeframe),
    enabled: !!symbol,
    staleTime: 120_000,
  })

  if (detailLoading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <LoadingSpinner size="lg" />
      </div>
    )
  }

  if (detailError || !detail) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-red-400">No analysis data for {symbol}.</p>
        <button
          onClick={() => navigate('/')}
          className="text-sm text-blue-400 hover:underline"
        >
          ← Back to scanner
        </button>
      </div>
    )
  }

  const chgPct = detail.meta.price_change_pct
  const chgColor = chgPct > 0 ? 'text-green-400' : chgPct < 0 ? 'text-red-400' : 'text-gray-400'

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3">
        <div className="max-w-screen-xl mx-auto flex items-center gap-4 flex-wrap">
          <button
            onClick={() => navigate('/')}
            className="text-sm text-gray-400 hover:text-gray-200 transition-colors shrink-0"
          >
            ← Back
          </button>
          <span className="font-bold text-xl text-white font-mono">{detail.symbol}</span>
          <span className="font-mono text-lg text-gray-200">${detail.meta.last_price.toFixed(2)}</span>
          <span className={`font-mono text-sm ${chgColor}`}>
            {chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%
          </span>
          <div className="flex items-center gap-1 ml-auto">
            <span className="text-xs text-gray-500 mr-2">Score</span>
            <ScoreDisplay score={detail.composite_score} showBar />
          </div>
          {detail.profile_matches.map((p) => (
            <ProfileBadge key={p} profile={p} />
          ))}
        </div>
      </header>

      <main className="max-w-screen-xl mx-auto px-6 py-4 space-y-4">
        {/* Timeframe selector + Chart */}
        <div>
          <div className="flex gap-1 mb-2">
            {(['1d', '1w'] as const).map((tf) => (
              <button
                key={tf}
                onClick={() => setChartTimeframe(tf)}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  chartTimeframe === tf
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                }`}
              >
                {tf === '1d' ? 'Daily' : 'Weekly'}
              </button>
            ))}
          </div>
          {chartLoading ? (
            <div className="flex justify-center items-center h-[420px] bg-gray-900 rounded">
              <LoadingSpinner size="lg" />
            </div>
          ) : ohlcv ? (
            <CandlestickChart data={ohlcv} height={420} detections={detail.chart_patterns ?? []} />
          ) : (
            <div className="flex justify-center items-center h-[420px] bg-gray-900/50 rounded border border-gray-700/40 text-gray-500 text-sm">
              No OHLCV data available. Trigger a data refresh first.
            </div>
          )}
        </div>

        {/* Category + Signals panels */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 p-4">
            <CategoryScoresPanel
              scores={detail.category_scores}
              selected={selectedCategory}
              onSelect={setSelectedCategory}
            />
          </div>
          <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 p-4 overflow-y-auto max-h-80">
            <SignalsPanel
              signals={detail.signals}
              highlightCategory={selectedCategory}
            />
          </div>
        </div>

        {/* Harmonic banner */}
        {detail.harmonics?.detected && (
          <HarmonicBanner harmonic={detail.harmonics} />
        )}

        {/* Chart patterns banner (YOLOv8) */}
        <ChartPatternsBanner
          patterns={detail.chart_patterns ?? []}
          scannedAt={detail.scanned_at}
        />

        {/* Volume contradiction warning */}
        {detail.volume_contradiction && (
          <div className="rounded-lg border border-yellow-700/40 bg-yellow-950/30 px-4 py-2 text-xs text-yellow-400">
            ⚠ Volume contradiction: OBV and CMF oppose the composite signal direction.
          </div>
        )}

        {/* Meta footer */}
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-500 pb-4">
          <span>ATR: <span className="text-gray-300">{detail.meta.atr.toFixed(4)}</span></span>
          <span>ATR%: <span className="text-gray-300">{detail.meta.atr_pct.toFixed(2)}%</span></span>
          <span>Vol ratio: <span className="text-gray-300">{detail.meta.volume_ratio.toFixed(2)}×</span></span>
          <span>Bars: <span className="text-gray-300">{detail.meta.bars}</span></span>
          <span>Last bar: <span className="text-gray-300">{detail.meta.timestamp.slice(0, 10)}</span></span>
        </div>
      </main>
    </div>
  )
}
