import type { MarketRegimeData, TimeSeriesData } from '../types';
import { apiFetch } from './client';

export const marketApi = {
  getRegime: (): Promise<MarketRegimeData> => apiFetch<MarketRegimeData>('/api/market/regime'),

  getBreadth: (): Promise<TimeSeriesData> => apiFetch<TimeSeriesData>('/api/market/breadth'),

  getMomentum: (): Promise<TimeSeriesData> => apiFetch<TimeSeriesData>('/api/market/momentum'),

  getMacro: (): Promise<TimeSeriesData> => apiFetch<TimeSeriesData>('/api/market/macro'),

  getSentiment: (): Promise<TimeSeriesData> => apiFetch<TimeSeriesData>('/api/market/sentiment'),

  triggerRefresh: (): Promise<{ status: string }> =>
    apiFetch<{ status: string }>('/api/market/refresh', { method: 'POST' }),
};
