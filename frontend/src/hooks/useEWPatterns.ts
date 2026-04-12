import { useQuery } from '@tanstack/react-query';
import { patternsApi } from '../api/scanner';
import type { EWDetection } from '../types';

export function useEWPatterns(symbol: string, timeframe: string = '1d') {
  return useQuery<EWDetection>({
    queryKey: ['ew-patterns', symbol, timeframe],
    queryFn: () => patternsApi.getEWDetection(symbol, timeframe),
    staleTime: 5 * 60 * 1000,
    enabled: !!symbol,
  });
}
