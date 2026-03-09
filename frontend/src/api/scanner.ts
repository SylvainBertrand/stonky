import type { EWDetection, ForecastData, OHLCVResponse, ScanRunResponse, ScanRunStatus, ScannerResult, SymbolPatterns } from '../types'

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

const FETCH_TIMEOUT_MS = 30_000

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const signal = AbortSignal.timeout(FETCH_TIMEOUT_MS)
  const res = await fetch(`${API_BASE}${path}`, { ...init, signal })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${body ? `: ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}

export const scannerApi = {
  getResults: (profile?: string | null, watchlistId?: number | null): Promise<ScannerResult[]> => {
    const params = new URLSearchParams()
    if (profile) params.set('profile', profile)
    if (watchlistId != null) params.set('watchlist_id', String(watchlistId))
    const qs = params.size > 0 ? `?${params.toString()}` : ''
    return apiFetch<ScannerResult[]>(`/api/scanner/results${qs}`)
  },

  runScan: (watchlistId?: number | null): Promise<ScanRunResponse> => {
    const qs = watchlistId != null ? `?watchlist_id=${watchlistId}` : ''
    return apiFetch<ScanRunResponse>(`/api/scanner/run${qs}`, { method: 'POST' })
  },

  getRunStatus: (runId: number): Promise<ScanRunStatus> =>
    apiFetch<ScanRunStatus>(`/api/scanner/runs/${runId}`),

  getDetail: (symbol: string, timeframe = '1d'): Promise<ScannerResult> =>
    apiFetch<ScannerResult>(
      `/api/scanner/results/${encodeURIComponent(symbol)}?timeframe=${timeframe}`,
    ),

  getOHLCV: (symbol: string, timeframe = '1d', bars = 200): Promise<OHLCVResponse> =>
    apiFetch<OHLCVResponse>(
      `/api/stocks/${encodeURIComponent(symbol)}/ohlcv?timeframe=${timeframe}&bars=${bars}`,
    ),
}

export const patternsApi = {
  getPatterns: (symbol: string, timeframe = '1d'): Promise<SymbolPatterns> =>
    apiFetch<SymbolPatterns>(
      `/api/patterns/${encodeURIComponent(symbol)}?timeframe=${timeframe}`,
    ),

  triggerScan: (watchlistId?: number | null): Promise<ScanRunResponse> => {
    const qs = watchlistId != null ? `?watchlist_id=${watchlistId}` : ''
    return apiFetch<ScanRunResponse>(`/api/patterns/scan${qs}`, { method: 'POST' })
  },

  getScanStatus: (): Promise<ScanRunStatus> =>
    apiFetch<ScanRunStatus>('/api/patterns/scan/status'),

  getEWDetection: (symbol: string, timeframe = '1d'): Promise<EWDetection> =>
    apiFetch<EWDetection>(
      `/api/patterns/elliott-wave/${encodeURIComponent(symbol)}?timeframe=${timeframe}`,
    ),
}

export const forecastsApi = {
  getForecast: (symbol: string, timeframe = '1d'): Promise<ForecastData | null> =>
    apiFetch<ForecastData | null>(
      `/api/forecasts/${encodeURIComponent(symbol)}?timeframe=${timeframe}`,
    ),

  triggerScan: (watchlistId?: number | null): Promise<ScanRunResponse> => {
    const qs = watchlistId != null ? `?watchlist_id=${watchlistId}` : ''
    return apiFetch<ScanRunResponse>(`/api/forecasts/scan${qs}`, { method: 'POST' })
  },

  getScanStatus: (): Promise<{ run_id: number; status: string; started_at: string | null; completed_at: string | null; symbols_scanned: number; symbols_forecast: number }> =>
    apiFetch('/api/forecasts/scan/status'),
}
