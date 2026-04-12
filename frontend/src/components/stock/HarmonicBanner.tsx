import type { HarmonicInfo } from '../../types';

interface Props {
  harmonic: HarmonicInfo;
}

export function HarmonicBanner({ harmonic }: Props) {
  if (!harmonic.detected) return null;

  const isBullish = harmonic.direction === 'bullish';
  const borderColor = isBullish ? 'border-green-700/50' : 'border-red-700/50';
  const bgColor = isBullish ? 'bg-green-950/40' : 'bg-red-950/40';
  const labelColor = isBullish ? 'text-green-400' : 'text-red-400';
  const qualityPct = Math.round(harmonic.ratio_quality * 100);

  return (
    <div className={`rounded-lg border ${borderColor} ${bgColor} px-4 py-3`}>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className={`font-semibold ${labelColor}`}>
          {harmonic.pattern ?? 'Harmonic'} ({harmonic.direction})
        </span>
        <span className="text-gray-400">
          Quality: <span className="text-gray-200 font-mono">{qualityPct}%</span>
        </span>
        {harmonic.in_prz && (
          <span className="bg-yellow-900/50 border border-yellow-700/40 rounded px-1.5 py-0.5 text-xs text-yellow-300 font-medium">
            In PRZ
          </span>
        )}
        {harmonic.prz_low != null && harmonic.prz_high != null && (
          <span className="text-gray-400">
            PRZ:{' '}
            <span className="text-gray-200 font-mono">
              ${harmonic.prz_low.toFixed(2)} – ${harmonic.prz_high.toFixed(2)}
            </span>
          </span>
        )}
        {harmonic.bars_since_completion != null && (
          <span className="text-gray-400">
            Point D:{' '}
            <span className="text-gray-200 font-mono">
              {harmonic.bars_since_completion} bars ago
            </span>
          </span>
        )}
      </div>
    </div>
  );
}
