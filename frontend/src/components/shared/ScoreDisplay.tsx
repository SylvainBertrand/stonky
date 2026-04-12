/** Returns Tailwind color classes based on score magnitude */
export function scoreColor(score: number): string {
  if (score >= 0.3) return 'text-green-400';
  if (score <= -0.3) return 'text-red-400';
  return 'text-gray-400';
}

interface Props {
  score: number;
  /** Show a mini horizontal bar alongside the number */
  showBar?: boolean;
}

export function ScoreDisplay({ score, showBar = false }: Props) {
  const color = scoreColor(score);
  const formatted = score.toFixed(2);

  if (!showBar) {
    return <span className={`font-mono text-sm font-semibold ${color}`}>{formatted}</span>;
  }

  const isPos = score >= 0;
  const magnitude = Math.min(1, Math.abs(score));
  const pct = `${Math.round(magnitude * 100)}%`;

  return (
    <div className="flex items-center gap-2">
      <span className={`font-mono text-sm font-semibold w-12 text-right ${color}`}>
        {formatted}
      </span>
      {/* Mini bar: negative fills left, positive fills right */}
      <div className="flex items-center w-20">
        <div className="flex-1 h-1.5 bg-gray-700 rounded-l overflow-hidden flex justify-end">
          {!isPos && <div className="h-full bg-red-500 rounded-l" style={{ width: pct }} />}
        </div>
        <div className="w-px h-2.5 bg-gray-500 shrink-0" />
        <div className="flex-1 h-1.5 bg-gray-700 rounded-r overflow-hidden">
          {isPos && <div className="h-full bg-green-500 rounded-r" style={{ width: pct }} />}
        </div>
      </div>
    </div>
  );
}
