import type { ForecastData } from '../../types';

interface Props {
  forecast: ForecastData | null | undefined;
}

function formatTimeAgo(isoString: string): string {
  const secs = Math.round((Date.now() - new Date(isoString).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  return `${Math.floor(secs / 3600)}h ago`;
}

export function ForecastBanner({ forecast }: Props) {
  if (!forecast) {
    return (
      <div className="flex items-center gap-3 px-3 py-2 rounded bg-gray-800/60 text-xs mb-2 text-gray-500">
        <span className="font-semibold text-gray-400">Chronos-2 Forecast</span>
        <span>Not yet forecasted</span>
      </div>
    );
  }

  const isBullish = forecast.direction === 'bullish';
  const isBearish = forecast.direction === 'bearish';
  const directionLabel = isBullish ? 'Bullish' : isBearish ? 'Bearish' : 'Neutral';
  const directionClass = isBullish
    ? 'text-green-400 bg-green-400/10'
    : isBearish
      ? 'text-red-400 bg-red-400/10'
      : 'text-gray-400 bg-gray-400/10';

  const moveSign = forecast.expected_move_pct >= 0 ? '+' : '';
  const rangeLow = forecast.forecast.quantile_10[forecast.forecast.quantile_10.length - 1];
  const rangeHigh = forecast.forecast.quantile_90[forecast.forecast.quantile_90.length - 1];

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded bg-gray-800/60 text-xs mb-2 flex-wrap">
      <span className="font-semibold text-gray-300">
        Chronos-2 Forecast ({forecast.horizon_bars}d)
      </span>
      <span className={`px-1.5 py-0.5 rounded font-medium ${directionClass}`}>
        {directionLabel}
      </span>
      <span className="text-gray-300">
        {moveSign}
        {forecast.expected_move_pct.toFixed(1)}% median
      </span>
      <span className="text-gray-500">
        {Math.round(forecast.direction_confidence * 100)}% confidence
      </span>
      <span className="text-gray-500">
        Range: ${rangeLow.toFixed(2)} – ${rangeHigh.toFixed(2)}
      </span>
      <span className="ml-auto text-gray-600">{formatTimeAgo(forecast.generated_at)}</span>
    </div>
  );
}
