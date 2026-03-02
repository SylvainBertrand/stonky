// ─── Scanner API types ────────────────────────────────────────────────────────

export interface CategoryScores {
  trend: number
  momentum: number
  volume: number
  volatility: number
  support_resistance: number
  divergence: number
  pattern: number
}

export interface AnalysisMeta {
  atr: number
  atr_pct: number
  last_price: number
  volume_ratio: number
  price_change_pct: number
  timestamp: string
  bars: number
}

export interface HarmonicInfo {
  detected: boolean
  pattern?: string
  direction?: string
  ratio_quality: number
  in_prz: boolean
  prz_low?: number
  prz_high?: number
  bars_since_completion?: number
}

export interface ScannerResult {
  symbol: string
  rank: number
  scanned_at: string  // ISO timestamp of when this analysis was cached
  composite_score: number
  category_scores: CategoryScores
  profile_matches: string[]
  signals: Record<string, number>
  meta: AnalysisMeta
  harmonics?: HarmonicInfo
  is_actionable: boolean
  volume_contradiction: boolean
}

export interface ProfileInfo {
  name: string
  description: string
  score_threshold: number
  required_conditions: string[]
}

// ─── OHLCV / Chart types ──────────────────────────────────────────────────────

export interface OHLCVBar {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface OverlayPoint {
  time: string
  value: number
}

export interface SupertrendPoint {
  time: string
  value: number
  direction: number // 1 = bullish, -1 = bearish
}

export interface OHLCVResponse {
  symbol: string
  bars: OHLCVBar[]
  overlays: {
    ema_21: OverlayPoint[]
    ema_50: OverlayPoint[]
    ema_200: OverlayPoint[]
    supertrend: SupertrendPoint[]
  }
}

// ─── Scanner run ─────────────────────────────────────────────────────────────

export interface ScanRunResponse {
  run_id: string
  status: string
  symbols_queued: number
}
