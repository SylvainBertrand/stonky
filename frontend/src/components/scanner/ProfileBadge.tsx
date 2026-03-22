const ABBREV: Record<string, string> = {
  MomentumBreakout: 'MB',
  MeanReversion: 'MR',
  TrendFollowing: 'TF',
  HarmonicSetup: 'HS',
}

const FULL_NAME: Record<string, string> = {
  MomentumBreakout: 'Momentum Breakout',
  MeanReversion: 'Mean Reversion',
  TrendFollowing: 'Trend Following',
  HarmonicSetup: 'Harmonic Setup',
}

export function ProfileBadge({ profile }: { profile: string }) {
  const label = ABBREV[profile] ?? profile.slice(0, 2).toUpperCase()
  const fullName = FULL_NAME[profile] ?? profile
  return (
    <span
      title={fullName}
      className="inline-block rounded px-1.5 py-0.5 text-xs font-semibold font-mono bg-green-900/60 text-green-300 border border-green-700/40"
    >
      {label}
    </span>
  )
}
