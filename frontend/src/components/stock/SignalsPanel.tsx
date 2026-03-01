import type { CategoryScores } from '../../types'
import { scoreColor } from '../shared/ScoreDisplay'

interface SignalMeta {
  label: string
  category: keyof CategoryScores
  interpret: (score: number) => string
}

const SIGNAL_INFO: Record<string, SignalMeta> = {
  ema_stack: {
    label: 'EMA Stack',
    category: 'trend',
    interpret: (s) =>
      s >= 0.9 ? '21>50>200 ✓' : s >= 0.3 ? '2 of 3 ✓' : s <= -0.9 ? '21<50<200' : s < 0 ? 'Bearish' : 'Neutral',
  },
  adx_dmi: {
    label: 'ADX/DMI',
    category: 'trend',
    interpret: (s) =>
      s > 0.5 ? 'Strong uptrend' : s > 0 ? 'Trending ↑' : s < -0.5 ? 'Strong downtrend' : s < 0 ? 'Trending ↓' : 'Ranging',
  },
  supertrend: {
    label: 'Supertrend',
    category: 'trend',
    interpret: (s) => (s > 0 ? 'Bullish' : s < 0 ? 'Bearish' : 'Neutral'),
  },
  rsi: {
    label: 'RSI',
    category: 'momentum',
    interpret: (s) =>
      s > 0.5 ? 'Oversold' : s > 0.2 ? 'Mild bullish' : s < -0.5 ? 'Overbought' : s < -0.2 ? 'Mild bearish' : 'Neutral',
  },
  macd: {
    label: 'MACD',
    category: 'momentum',
    interpret: (s) =>
      s > 0.5 ? 'Bull cross' : s > 0 ? 'Positive' : s < -0.5 ? 'Bear cross' : s < 0 ? 'Negative' : 'Neutral',
  },
  stochastic: {
    label: 'Stochastic',
    category: 'momentum',
    interpret: (s) =>
      s > 0.5 ? 'Oversold' : s > 0 ? 'Bullish' : s < -0.5 ? 'Overbought' : s < 0 ? 'Bearish' : 'Neutral',
  },
  obv: {
    label: 'OBV',
    category: 'volume',
    interpret: (s) => (s > 0.3 ? 'Rising' : s < -0.3 ? 'Declining' : 'Flat'),
  },
  vwap: {
    label: 'VWAP',
    category: 'volume',
    interpret: (s) => (s > 0 ? 'Above VWAP' : s < 0 ? 'Below VWAP' : 'At VWAP'),
  },
  cmf: {
    label: 'CMF',
    category: 'volume',
    interpret: (s) => (s > 0.1 ? 'Accumulation' : s < -0.1 ? 'Distribution' : 'Neutral'),
  },
  bb_pct_b: {
    label: 'BB %B',
    category: 'volatility',
    interpret: (s) =>
      s > 0.5 ? 'Near lower band' : s < -0.5 ? 'Near upper band' : 'Mid range',
  },
  ttm_squeeze: {
    label: 'TTM Squeeze',
    category: 'volatility',
    interpret: (s) =>
      s >= 0.7 ? 'Fired ↑' : s <= -0.7 ? 'Fired ↓' : s > 0 ? 'Building' : s < -0.1 ? 'In squeeze' : 'No squeeze',
  },
  atr: {
    label: 'ATR',
    category: 'volatility',
    interpret: () => 'Sizing only',
  },
  fibonacci: {
    label: 'Fibonacci',
    category: 'support_resistance',
    interpret: (s) =>
      s > 0.5 ? 'At support' : s < -0.5 ? 'At resistance' : s !== 0 ? 'Near level' : 'No level',
  },
  pivot_points: {
    label: 'Pivot Points',
    category: 'support_resistance',
    interpret: (s) =>
      s > 0.3 ? 'Near support' : s < -0.3 ? 'Near resistance' : 'Between levels',
  },
  rsi_divergence: {
    label: 'RSI Divergence',
    category: 'divergence',
    interpret: (s) => (s > 0 ? 'Bullish' : s < 0 ? 'Bearish' : 'None'),
  },
  macd_divergence: {
    label: 'MACD Divergence',
    category: 'divergence',
    interpret: (s) => (s > 0 ? 'Bullish' : s < 0 ? 'Bearish' : 'None'),
  },
  candlestick: {
    label: 'Candlestick',
    category: 'pattern',
    interpret: (s) =>
      s > 0.5 ? 'Bullish pattern' : s < -0.5 ? 'Bearish pattern' : s > 0 ? 'Mild bullish' : s < 0 ? 'Mild bearish' : 'None',
  },
}

interface Props {
  signals: Record<string, number>
  highlightCategory?: keyof CategoryScores | null
}

export function SignalsPanel({ signals, highlightCategory }: Props) {
  const signalKeys = Object.keys(SIGNAL_INFO).filter((k) => k in signals)

  const filtered = highlightCategory
    ? signalKeys.filter((k) => SIGNAL_INFO[k]?.category === highlightCategory)
    : signalKeys

  return (
    <div>
      <h3 className="text-xs font-semibold uppercase tracking-widest text-gray-500 mb-3">
        Individual Signals
        {highlightCategory && (
          <span className="ml-2 text-blue-400 normal-case">
            ({highlightCategory.replace('_', ' ')})
          </span>
        )}
      </h3>
      <div className="space-y-1">
        {filtered.map((key) => {
          const info = SIGNAL_INFO[key]
          if (!info) return null
          const score = signals[key] ?? 0
          const interpretation = info.interpret(score)

          return (
            <div key={key} className="flex items-center gap-2 py-1 px-2 rounded hover:bg-gray-800/40">
              <span className="text-xs text-gray-300 w-32 shrink-0">{info.label}</span>
              <span className={`text-xs font-mono font-semibold w-12 text-right ${scoreColor(score)}`}>
                {score.toFixed(3)}
              </span>
              <span className="text-xs text-gray-500">{interpretation}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
