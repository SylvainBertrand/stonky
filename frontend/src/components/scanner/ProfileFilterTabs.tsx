const PROFILES = [
  { key: null, label: 'All' },
  { key: 'MomentumBreakout', label: 'Momentum Breakout' },
  { key: 'MeanReversion', label: 'Mean Reversion' },
  { key: 'TrendFollowing', label: 'Trend Following' },
  { key: 'HarmonicSetup', label: 'Harmonic Setup' },
]

interface Props {
  active: string | null
  onChange: (profile: string | null) => void
}

export function ProfileFilterTabs({ active, onChange }: Props) {
  return (
    <div className="flex flex-wrap gap-1">
      {PROFILES.map(({ key, label }) => {
        const isActive = active === key
        return (
          <button
            key={key ?? 'all'}
            onClick={() => onChange(key)}
            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
              isActive
                ? 'bg-blue-600 text-white'
                : 'bg-gray-800 text-gray-400 hover:bg-gray-700 hover:text-gray-200'
            }`}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}
