export type OverlayKey = 'ema21' | 'ema50' | 'ema200' | 'supertrend' | 'volume' | 'patterns'
export type OverlayToggles = Record<OverlayKey, boolean>

export const DEFAULT_OVERLAYS: OverlayToggles = {
  ema21: true,
  ema50: true,
  ema200: true,
  supertrend: true,
  volume: true,
  patterns: true,
}

interface Props {
  overlays: OverlayToggles
  onToggle: (key: OverlayKey) => void
  onReset: () => void
}

const EMA_DOTS: Partial<Record<OverlayKey, string>> = {
  ema21: '#3b82f6',   // blue
  ema50: '#f97316',   // orange
  ema200: '#6b7280',  // gray
}

const BUTTON_LABELS: Record<OverlayKey, string> = {
  ema21: 'EMA 21',
  ema50: 'EMA 50',
  ema200: 'EMA 200',
  supertrend: 'Supertrend',
  volume: 'Volume',
  patterns: 'Patterns',
}

const OVERLAY_KEYS: OverlayKey[] = ['ema21', 'ema50', 'ema200', 'supertrend', 'volume', 'patterns']

export function ChartControls({ overlays, onToggle, onReset }: Props) {
  return (
    <div className="flex items-center gap-1 mb-2 flex-wrap">
      {OVERLAY_KEYS.map((key) => {
        const active = overlays[key]
        const dotColor = EMA_DOTS[key]
        return (
          <button
            key={key}
            aria-pressed={active}
            onClick={() => onToggle(key)}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs font-medium transition-colors ${
              active
                ? 'bg-gray-700 text-gray-100'
                : 'bg-gray-800/60 text-gray-500 hover:text-gray-300'
            }`}
          >
            {dotColor && (
              <span
                data-dot
                style={{ backgroundColor: dotColor }}
                className="inline-block w-2 h-2 rounded-full"
              />
            )}
            {BUTTON_LABELS[key]}
          </button>
        )
      })}
      <button
        onClick={onReset}
        className="ml-auto px-2 py-1 rounded text-xs font-medium bg-gray-800/60 text-gray-400 hover:text-gray-200 transition-colors"
        title="Reset view"
      >
        ↺ Reset
      </button>
    </div>
  )
}
