import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { marketApi } from '../../api/market';

const REGIME_COLORS: Record<string, string> = {
  bull_trending: 'text-green-400',
  bull_extended: 'text-yellow-400',
  choppy: 'text-yellow-500',
  bear_warning: 'text-orange-400',
  bear: 'text-red-400',
  unknown: 'text-gray-500',
};
const REGIME_DOTS: Record<string, string> = {
  bull_trending: 'bg-green-400',
  bull_extended: 'bg-yellow-400',
  choppy: 'bg-yellow-500',
  bear_warning: 'bg-orange-400',
  bear: 'bg-red-400',
  unknown: 'bg-gray-500',
};
const REGIME_LABELS: Record<string, string> = {
  bull_trending: 'Bull Trending',
  bull_extended: 'Bull Extended',
  choppy: 'Choppy',
  bear_warning: 'Bear Warning',
  bear: 'Bear',
  unknown: 'No Data',
};

export function MarketRegimeStrip() {
  const { data: regime } = useQuery({
    queryKey: ['market', 'regime'],
    queryFn: marketApi.getRegime,
    staleTime: 5 * 60 * 1000,
  });
  if (!regime) return null;
  const dotColor = REGIME_DOTS[regime.regime] ?? REGIME_DOTS.unknown;
  const textColor = REGIME_COLORS[regime.regime] ?? REGIME_COLORS.unknown;
  const label = REGIME_LABELS[regime.regime] ?? regime.regime;
  return (
    <Link
      to="/market"
      className="flex items-center gap-2 px-4 py-1.5 bg-gray-900/60 border border-gray-800 rounded-lg hover:bg-gray-800/60 transition-colors text-sm"
    >
      <span className={`w-2 h-2 rounded-full ${dotColor}`} />
      <span className={`font-medium ${textColor}`}>{label}</span>
      <span className="text-gray-500">—</span>
      <span className="text-gray-400">{regime.scanner_implication}</span>
    </Link>
  );
}
