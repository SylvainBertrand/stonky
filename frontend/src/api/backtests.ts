import type { BacktestResponse, SweepResponse, BacktestHistoryItem } from '../types'
import { apiFetch } from './client'

export interface BacktestRequest {
  symbol: string
  timeframe: string
  start_date: string
  end_date: string
  initial_capital: number
  strategy_type: string
  parameters: Record<string, unknown>
}

export interface SweepRequest {
  symbol: string
  timeframe: string
  start_date: string
  end_date: string
  initial_capital: number
  strategy_type: string
  param_ranges: Record<string, [number, number, number]> // [min, max, step]
}

export const backtestApi = {
  run: (req: BacktestRequest): Promise<BacktestResponse> =>
    apiFetch<BacktestResponse>('/api/backtests/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    }),

  sweep: (req: SweepRequest): Promise<SweepResponse> =>
    apiFetch<SweepResponse>('/api/backtests/sweep', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(req),
    }),

  getHistory: (): Promise<BacktestHistoryItem[]> =>
    apiFetch<BacktestHistoryItem[]>('/api/backtests/history'),

  getById: (id: number): Promise<BacktestResponse> =>
    apiFetch<BacktestResponse>(`/api/backtests/${id}`),

  delete: (id: number): Promise<void> =>
    apiFetch<void>(`/api/backtests/${id}`, { method: 'DELETE' }),
}
