import { useQuery } from '@tanstack/react-query'
import { forecastsApi } from '../api/scanner'
import type { ForecastData } from '../types'

export function useForecast(symbol: string, timeframe: string = '1d') {
  return useQuery<ForecastData | null>({
    queryKey: ['forecast', symbol, timeframe],
    queryFn: () => forecastsApi.getForecast(symbol, timeframe),
    staleTime: 10 * 60 * 1000,
    enabled: !!symbol,
  })
}
