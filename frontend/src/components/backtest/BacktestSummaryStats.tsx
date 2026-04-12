import type { BacktestStats } from '../../types';

interface Props {
  stats: BacktestStats;
  benchmarkReturn: number;
  benchmarkSharpe: number;
}

function formatPercent(value: number): string {
  const sign = value >= 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}

function formatRatio(value: number): string {
  return value.toFixed(2);
}

function getStatColor(value: number, isNegativeBetter?: boolean): string {
  if (isNegativeBetter) {
    return value <= 0 ? 'text-green-400' : 'text-red-400';
  }
  return value >= 0 ? 'text-green-400' : 'text-red-400';
}

export function BacktestSummaryStats({ stats, benchmarkReturn, benchmarkSharpe }: Props) {
  const statsArray = [
    {
      label: 'Total Return',
      value: formatPercent(stats.total_return_pct),
      color: getStatColor(stats.total_return_pct),
    },
    { label: 'CAGR', value: formatPercent(stats.cagr_pct), color: getStatColor(stats.cagr_pct) },
    {
      label: 'Sharpe Ratio',
      value: formatRatio(stats.sharpe_ratio),
      color: getStatColor(stats.sharpe_ratio),
    },
    {
      label: 'Sortino Ratio',
      value: formatRatio(stats.sortino_ratio),
      color: getStatColor(stats.sortino_ratio),
    },
    {
      label: 'Max Drawdown',
      value: formatPercent(stats.max_drawdown_pct),
      color: getStatColor(stats.max_drawdown_pct, true),
    },
    {
      label: 'Win Rate',
      value: formatPercent(stats.win_rate_pct),
      color: getStatColor(stats.win_rate_pct),
    },
    {
      label: 'Profit Factor',
      value: formatRatio(stats.profit_factor),
      color: getStatColor(stats.profit_factor),
    },
    { label: 'Trades', value: String(stats.total_trades), color: 'text-gray-400' },
  ];

  const returnDiff = stats.total_return_pct - benchmarkReturn;
  const sharpeDiff = stats.sharpe_ratio - benchmarkSharpe;

  return (
    <div className="space-y-4">
      {/* Stats Grid */}
      <div className="grid grid-cols-4 gap-4">
        {statsArray.map((stat) => (
          <div key={stat.label} className="rounded-lg border border-gray-800 bg-gray-900/50 p-3">
            <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">
              {stat.label}
            </div>
            <div className={`text-xl font-bold font-mono ${stat.color}`}>{stat.value}</div>
          </div>
        ))}
      </div>

      {/* Benchmark Comparison */}
      <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-3">
        <div className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2">
          vs Buy & Hold
        </div>
        <div className="flex items-baseline gap-4">
          <div>
            <span className={`font-mono text-sm font-semibold ${getStatColor(returnDiff)}`}>
              {formatPercent(returnDiff)}
            </span>
            <span className="text-xs text-gray-500 ml-2">
              ({formatPercent(benchmarkReturn)} benchmark)
            </span>
          </div>
          <div>
            <span className={`font-mono text-sm font-semibold ${getStatColor(sharpeDiff)}`}>
              {formatRatio(sharpeDiff)}pp Sharpe
            </span>
            <span className="text-xs text-gray-500 ml-2">
              ({formatRatio(benchmarkSharpe)} benchmark)
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
