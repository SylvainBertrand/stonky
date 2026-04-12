import type { EWDetection } from '../../types';

interface Props {
  detection: EWDetection | undefined;
}

function formatPosition(pos: string | null): string {
  if (!pos) return '';
  // "wave_3" → "Wave 3", "wave_5_complete" → "Wave 5 (Complete)"
  return pos.replace('wave_', 'Wave ').replace('_complete', ' (Complete)').replace(/_/g, ' ');
}

export function ElliottWaveBanner({ detection }: Props) {
  if (!detection || detection.wave_type === null) return null;

  const isBullish = detection.direction === 'bullish';
  const directionLabel = isBullish ? 'Bullish' : 'Bearish';
  const directionClass = isBullish
    ? 'text-green-400 bg-green-400/10'
    : 'text-red-400 bg-red-400/10';
  const waveTypeLabel = detection.wave_type === 'impulse' ? 'Impulse' : 'Corrective';

  return (
    <div className="flex items-center gap-3 px-3 py-2 rounded bg-gray-800/60 text-xs mb-2">
      <span className="font-semibold text-gray-300">Elliott Wave</span>
      <span className="text-gray-400">{waveTypeLabel}</span>
      <span className={`px-1.5 py-0.5 rounded font-medium ${directionClass}`}>
        {directionLabel}
      </span>
      {detection.current_position && (
        <span className="text-gray-300 font-medium">
          {formatPosition(detection.current_position)}
        </span>
      )}
      <span className="ml-auto text-gray-500">{Math.round(detection.confidence * 100)}%</span>
    </div>
  );
}
