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

export interface ChartPatternDetection {
  pattern: string
  direction: 'bullish' | 'bearish' | 'neutral'
  confidence: number
  bar_start: number
  bar_end: number
  price_top?: number
  price_bottom?: number
}

export interface SymbolPatterns {
  symbol: string
  scanned_at: string | null
  detections: ChartPatternDetection[]
}

export interface EWWavePoint {
  time: string
  price: number
  label: string
  bar_index: number
}

export interface EWDetection {
  symbol: string
  wave_type: 'impulse' | 'corrective' | null
  direction: 'bullish' | 'bearish' | null
  current_position: string | null
  confidence: number
  waves: EWWavePoint[]
}

export interface ForecastQuantiles {
  median: number[]
  quantile_10: number[]
  quantile_25: number[]
  quantile_75: number[]
  quantile_90: number[]
}

export interface ForecastData {
  symbol: string
  timeframe: string
  generated_at: string
  last_bar_date: string
  last_close: number
  horizon_bars: number
  direction: 'bullish' | 'bearish' | 'neutral'
  direction_confidence: number
  expected_move_pct: number
  forecast: ForecastQuantiles
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
  chart_patterns?: ChartPatternDetection[]
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
  run_id: number
  status: string
  symbols_queued: number
}

export interface ScanRunStatus {
  run_id: number
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  started_at: string | null
  completed_at: string | null
  error_message: string | null
  symbols_scanned: number
  symbols_scored: number
}

// ─── Watchlist types ──────────────────────────────────────────────────────────

export interface Watchlist {
  id: number
  name: string
  description: string | null
  is_default: boolean
  created_at: string
  item_count: number
}

export interface WatchlistItemWithRatings {
  id: number
  symbol_id: number
  ticker: string
  name: string | null
  notes: string | null
  added_at: string
  quant_score: number | null
  momentum_grade: string | null
  valuation_grade: string | null
  growth_grade: string | null
}

export interface SAImportResult {
  added: number
  skipped: number
  ratings_imported: number
  errors: number
}
