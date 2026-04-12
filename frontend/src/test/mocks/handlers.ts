import { http, HttpResponse } from 'msw';
import type { ScannerResult, ScanRunStatus } from '../../types';

// ---------------------------------------------------------------------------
// Shared fixture data
// ---------------------------------------------------------------------------

export function makeScannerResult(overrides: Partial<ScannerResult> = {}): ScannerResult {
  return {
    symbol: 'AAPL',
    rank: 1,
    scanned_at: new Date().toISOString(),
    composite_score: 0.65,
    category_scores: {
      trend: 0.7,
      momentum: 0.5,
      volume: 0.4,
      volatility: 0.1,
      support_resistance: 0.2,
      divergence: 0.0,
      pattern: 0.0,
    },
    profile_matches: ['MomentumBreakout'],
    signals: { rsi: 0.4, ema_trend: 0.6 },
    meta: {
      atr: 2.5,
      atr_pct: 2.0,
      last_price: 185.5,
      volume_ratio: 1.2,
      price_change_pct: 0.8,
      timestamp: new Date().toISOString(),
      bars: 250,
    },
    harmonics: undefined,
    is_actionable: true,
    volume_contradiction: false,
    ...overrides,
  };
}

export const MOCK_RESULTS: ScannerResult[] = [
  makeScannerResult({ symbol: 'AAPL', rank: 1, composite_score: 0.65 }),
  makeScannerResult({
    symbol: 'MSFT',
    rank: 2,
    composite_score: 0.5,
    is_actionable: false,
    profile_matches: [],
  }),
  makeScannerResult({ symbol: 'NVDA', rank: 3, composite_score: -0.2, is_actionable: false }),
];

export const MOCK_RUN_PENDING: ScanRunStatus = {
  run_id: 1,
  status: 'pending',
  started_at: null,
  completed_at: null,
  error_message: null,
  symbols_scanned: 3,
  symbols_scored: 0,
};

export const MOCK_RUN_COMPLETED: ScanRunStatus = {
  run_id: 1,
  status: 'completed',
  started_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
  error_message: null,
  symbols_scanned: 3,
  symbols_scored: 3,
};

export const MOCK_RUN_FAILED: ScanRunStatus = {
  run_id: 1,
  status: 'failed',
  started_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
  error_message: 'DB connection timeout',
  symbols_scanned: 3,
  symbols_scored: 0,
};

// ---------------------------------------------------------------------------
// Default handlers (used by all tests unless overridden with server.use())
// ---------------------------------------------------------------------------

export const handlers = [
  http.get('/api/health', () => {
    return HttpResponse.json({ status: 'ok', db: 'connected' });
  }),

  http.get('/api/watchlists', () => {
    return HttpResponse.json([
      { id: 1, name: 'Tech Stocks', description: 'Top technology picks', is_default: true },
      { id: 2, name: 'Dividend Growth', description: null, is_default: false },
    ]);
  }),

  // Scanner endpoints
  http.post('/api/scanner/run', () => {
    return HttpResponse.json({ run_id: 1, status: 'queued', symbols_queued: 3 }, { status: 202 });
  }),

  http.get('/api/scanner/runs/:runId', () => {
    return HttpResponse.json(MOCK_RUN_COMPLETED);
  }),

  http.get('/api/scanner/results', () => {
    return HttpResponse.json(MOCK_RESULTS);
  }),

  http.get('/api/scanner/profiles', () => {
    return HttpResponse.json([
      {
        name: 'MomentumBreakout',
        description: 'Momentum breakout setups',
        score_threshold: 0.5,
        required_conditions: ['rsi > 0'],
      },
      {
        name: 'MeanReversion',
        description: 'Mean reversion setups',
        score_threshold: 0.4,
        required_conditions: [],
      },
      {
        name: 'TrendFollowing',
        description: 'Trend following setups',
        score_threshold: 0.45,
        required_conditions: [],
      },
      {
        name: 'HarmonicSetup',
        description: 'Harmonic pattern setups',
        score_threshold: 0.3,
        required_conditions: [],
      },
    ]);
  }),
];
