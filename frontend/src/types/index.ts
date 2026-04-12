// ─── Scanner API types ────────────────────────────────────────────────────────

export interface CategoryScores {
  trend: number;
  momentum: number;
  volume: number;
  volatility: number;
  support_resistance: number;
  divergence: number;
  pattern: number;
}

export interface AnalysisMeta {
  atr: number;
  atr_pct: number;
  last_price: number;
  volume_ratio: number;
  price_change_pct: number;
  timestamp: string;
  bars: number;
}

export interface HarmonicInfo {
  detected: boolean;
  pattern?: string;
  direction?: string;
  ratio_quality: number;
  in_prz: boolean;
  prz_low?: number;
  prz_high?: number;
  bars_since_completion?: number;
}

export interface ChartPatternDetection {
  pattern: string;
  direction: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  bar_start: number;
  bar_end: number;
  price_top?: number;
  price_bottom?: number;
}

export interface SymbolPatterns {
  symbol: string;
  scanned_at: string | null;
  detections: ChartPatternDetection[];
}

export interface EWWavePoint {
  time: string;
  price: number;
  label: string;
  bar_index: number;
}

export interface EWDetection {
  symbol: string;
  wave_type: 'impulse' | 'corrective' | null;
  direction: 'bullish' | 'bearish' | null;
  current_position: string | null;
  confidence: number;
  waves: EWWavePoint[];
}

export interface ForecastQuantiles {
  median: number[];
  quantile_10: number[];
  quantile_25: number[];
  quantile_75: number[];
  quantile_90: number[];
}

export interface ForecastData {
  symbol: string;
  timeframe: string;
  generated_at: string;
  last_bar_date: string;
  last_close: number;
  horizon_bars: number;
  direction: 'bullish' | 'bearish' | 'neutral';
  direction_confidence: number;
  expected_move_pct: number;
  forecast: ForecastQuantiles;
}

export interface SynthesisData {
  symbol: string;
  generated_at: string;
  setup_type: string;
  bias: 'bullish' | 'bearish' | 'neutral';
  confidence: 'high' | 'medium' | 'low';
  summary: string;
  signal_confluence: string;
  signal_conflicts: string;
  entry: number | null;
  stop: number | null;
  target: number | null;
  risk_reward: number | null;
  key_risk: string;
  parse_error: boolean;
}

export interface ScannerResult {
  symbol: string;
  rank: number;
  scanned_at: string; // ISO timestamp of when this analysis was cached
  composite_score: number;
  category_scores: CategoryScores;
  profile_matches: string[];
  signals: Record<string, number>;
  meta: AnalysisMeta | null;
  harmonics?: HarmonicInfo;
  chart_patterns?: ChartPatternDetection[];
  is_actionable: boolean;
  volume_contradiction: boolean;
  needs_scan?: boolean;
}

export interface ProfileInfo {
  name: string;
  description: string;
  score_threshold: number;
  required_conditions: string[];
}

// ─── OHLCV / Chart types ──────────────────────────────────────────────────────

export interface OHLCVBar {
  time: string | number; // string (YYYY-MM-DD) for daily+, number (Unix timestamp) for intraday
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface OverlayPoint {
  time: string | number;
  value: number;
}

export interface SupertrendPoint {
  time: string | number;
  value: number;
  direction: number; // 1 = bullish, -1 = bearish
}

export interface OHLCVResponse {
  symbol: string;
  bars: OHLCVBar[];
  has_more: boolean;
  overlays: {
    ema_21: OverlayPoint[];
    ema_50: OverlayPoint[];
    ema_200: OverlayPoint[];
    supertrend: SupertrendPoint[];
  };
}

// ─── Scanner run ─────────────────────────────────────────────────────────────

export interface ScanRunResponse {
  run_id: number;
  status: string;
  symbols_queued: number;
}

export interface ScanRunStatus {
  run_id: number;
  status: 'pending' | 'running' | 'completed' | 'failed' | string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  symbols_scanned: number;
  symbols_scored: number;
}

// ─── Watchlist types ──────────────────────────────────────────────────────────

export interface Watchlist {
  id: number;
  name: string;
  description: string | null;
  is_default: boolean;
  created_at: string;
  item_count: number;
}

export interface WatchlistItemWithRatings {
  id: number;
  symbol_id: number;
  ticker: string;
  name: string | null;
  notes: string | null;
  added_at: string;
  quant_score: number | null;
  momentum_grade: string | null;
  valuation_grade: string | null;
  growth_grade: string | null;
}

export interface SAImportResult {
  added: number;
  skipped: number;
  ratings_imported: number;
  errors: number;
}

// ─── Backtest types ───────────────────────────────────────────────────────

export interface BacktestStats {
  total_return_pct: number;
  cagr_pct: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown_pct: number;
  max_drawdown_duration_days: number;
  win_rate_pct: number;
  profit_factor: number;
  total_trades: number;
  avg_trade_pct: number;
  avg_win_pct: number;
  avg_loss_pct: number;
}

export interface BacktestTrade {
  entry_date: string;
  exit_date: string;
  entry_price: number;
  exit_price: number;
  pnl_pct: number;
  pnl_abs: number;
  direction: string;
}

export interface EquityCurvePoint {
  date: string;
  value: number;
}

export interface DrawdownPoint {
  date: string;
  pct: number;
}

export interface BacktestResponse {
  id: number | null;
  stats: BacktestStats;
  equity_curve: EquityCurvePoint[];
  drawdown_curve: DrawdownPoint[];
  trades: BacktestTrade[];
  benchmark_return_pct: number;
  benchmark_sharpe: number;
}

export interface SweepResponse {
  results: BacktestResponse[];
  best_index: number;
  heatmap_data: Record<string, number>;
}

export interface BacktestHistoryItem {
  id: number;
  created_at: string;
  symbol: string;
  timeframe: string;
  strategy: string;
  total_return_pct: number;
  sharpe_ratio: number;
  total_trades: number;
}

export type StrategyType =
  | 'ema_crossover'
  | 'rsi_threshold'
  | 'macd_cross'
  | 'supertrend'
  | 'momentum_breakout'
  | 'trend_following'
  | 'mean_reversion'
  | 'harmonic_setup'
  | 'yolo_pattern'
  | 'custom';

// ─── Market module types ──────────────────────────────────────────────────

export interface MarketRegimeData {
  as_of_date: string | null;
  regime: string;
  breadth: string;
  momentum: string;
  sentiment: string;
  macro: string;
  summary: string;
  scanner_implication: string;
}

export interface TimeSeriesItem {
  name: string;
  data: (number | null)[];
}

export interface TimeSeriesData {
  labels: string[];
  series: TimeSeriesItem[];
}
