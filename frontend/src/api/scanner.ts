import type { OHLCVResponse, ScanRunResponse, ScannerResult } from '../types'

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${body ? `: ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}

export const scannerApi = {
  getResults: (profile?: string | null): Promise<ScannerResult[]> => {
    const qs = profile ? `?profile=${encodeURIComponent(profile)}` : ''
    return apiFetch<ScannerResult[]>(`/api/scanner/results${qs}`)
  },

  runScan: (): Promise<ScanRunResponse> =>
    apiFetch<ScanRunResponse>('/api/scanner/run', { method: 'POST' }),

  getDetail: (symbol: string): Promise<ScannerResult> =>
    apiFetch<ScannerResult>(`/api/scanner/results/${encodeURIComponent(symbol)}`),

  getOHLCV: (symbol: string, timeframe = '1d', bars = 200): Promise<OHLCVResponse> =>
    apiFetch<OHLCVResponse>(
      `/api/stocks/${encodeURIComponent(symbol)}/ohlcv?timeframe=${timeframe}&bars=${bars}`,
    ),
}
