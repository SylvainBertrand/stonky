import type { MarketRegimeData } from '../../types'

const REGIME_COLORS: Record<string, string> = {
  bull_trending: 'text-green-400',
  bull_extended: 'text-yellow-400',
  choppy: 'text-yellow-500',
  bear_warning: 'text-orange-400',
  bear: 'text-red-400',
  unknown: 'text-gray-500',
}
const REGIME_DOTS: Record<string, string> = {
  bull_trending: 'bg-green-400',
  bull_extended: 'bg-yellow-400',
  choppy: 'bg-yellow-500',
  bear_warning: 'bg-orange-400',
  bear: 'bg-red-400',
  unknown: 'bg-gray-500',
}
const REGIME_LABELS: Record<string, string> = {
  bull_trending: 'Bull Trending',
  bull_extended: 'Bull Extended',
  choppy: 'Choppy',
  bear_warning: 'Bear Warning',
  bear: 'Bear',
  unknown: 'No Data',
}

interface MarketRegimeBannerProps {
  regime: MarketRegimeData
}

export function MarketRegimeBanner({ regime }: MarketRegimeBannerProps) {
  const dotColor = REGIME_DOTS[regime.regime] ?? REGIME_DOTS.unknown
  const textColor = REGIME_COLORS[regime.regime] ?? REGIME_COLORS.unknown
  const label = REGIME_LABELS[regime.regime] ?? regime.regime

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-6">
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className={`w-3 h-3 rounded-full ${dotColor}`} />
          <h2 className={`text-2xl font-bold ${textColor}`}>{label}</h2>
        </div>
        {regime.as_of_date && (
          <span className="text-sm text-gray-500">
            As of {new Date(regime.as_of_date).toLocaleDateString()}
          </span>
        )}
      </div>

      {/* Pills */}
      <div className="flex gap-2 mb-4 flex-wrap">
        <div className="px-3 py-1 rounded-full bg-gray-800 text-xs font-medium text-gray-300">
          Breadth: <span className="text-gray-100">{regime.breadth}</span>
        </div>
        <div className="px-3 py-1 rounded-full bg-gray-800 text-xs font-medium text-gray-300">
          Momentum: <span className="text-gray-100">{regime.momentum}</span>
        </div>
        <div className="px-3 py-1 rounded-full bg-gray-800 text-xs font-medium text-gray-300">
          Sentiment: <span className="text-gray-100">{regime.sentiment}</span>
        </div>
        <div className="px-3 py-1 rounded-full bg-gray-800 text-xs font-medium text-gray-300">
          Macro: <span className="text-gray-100">{regime.macro}</span>
        </div>
      </div>

      {/* Summary */}
      <p className="text-gray-400 text-sm mb-2">{regime.summary}</p>

      {/* Scanner implication */}
      <div className="border-t border-gray-800 pt-3 mt-3">
        <p className="text-xs font-medium text-gray-500 mb-1">Scanner Implication</p>
        <p className="text-sm text-gray-300">{regime.scanner_implication}</p>
      </div>
    </div>
  )
}
