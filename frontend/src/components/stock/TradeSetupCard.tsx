import type { SynthesisData } from '../../types';
import { LoadingSpinner } from '../shared/LoadingSpinner';

interface TradeSetupCardProps {
  synthesis: SynthesisData | null | undefined;
  isLoading?: boolean;
}

function formatTimeAgo(isoString: string): string {
  const secs = Math.round((Date.now() - new Date(isoString).getTime()) / 1000);
  if (secs < 60) return `${secs}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

function getDirectionStyles(bias: 'bullish' | 'bearish' | 'neutral') {
  const styles: Record<
    string,
    { border: string; bg: string; text: string; header: string; dot: string }
  > = {
    bullish: {
      border: 'border-green-700/50',
      bg: 'bg-green-950/30',
      text: 'text-green-400',
      header: 'bg-green-900/40',
      dot: 'text-green-400',
    },
    bearish: {
      border: 'border-red-700/50',
      bg: 'bg-red-950/30',
      text: 'text-red-400',
      header: 'bg-red-900/40',
      dot: 'text-red-400',
    },
    neutral: {
      border: 'border-gray-700/50',
      bg: 'bg-gray-900/40',
      text: 'text-gray-400',
      header: 'bg-gray-800/40',
      dot: 'text-gray-500',
    },
  };
  return styles[bias];
}

function getConfidenceBadgeClass(confidence: 'high' | 'medium' | 'low') {
  const classes: Record<string, { base: string; text: string; label: string }> = {
    high: { base: 'bg-green-900/50 border-green-700/40', text: 'text-green-300', label: 'H' },
    medium: { base: 'bg-yellow-900/50 border-yellow-700/40', text: 'text-yellow-300', label: 'M' },
    low: { base: 'bg-gray-800/50 border-gray-700/40', text: 'text-gray-400', label: 'L' },
  };
  return classes[confidence];
}

export function TradeSetupCard({ synthesis, isLoading }: TradeSetupCardProps) {
  if (isLoading) {
    return (
      <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 px-4 py-3">
        <div className="flex items-center justify-center gap-2">
          <LoadingSpinner size="sm" />
          <span className="text-sm text-gray-400">Loading trade setup analysis...</span>
        </div>
      </div>
    );
  }

  if (!synthesis) {
    return (
      <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 px-4 py-3">
        <div className="flex items-center justify-between">
          <span className="text-gray-500 font-medium">Trade Setup Analysis</span>
          <span className="text-gray-600 text-xs">Analysis not yet generated</span>
        </div>
      </div>
    );
  }

  const directionStyles = getDirectionStyles(synthesis.bias);
  const confidenceBadge = getConfidenceBadgeClass(synthesis.confidence);

  return (
    <div className={`rounded-lg border ${directionStyles.border} ${directionStyles.bg}`}>
      {/* Header with setup info */}
      <div
        className={`px-4 py-3 ${directionStyles.header} border-b ${directionStyles.border} rounded-t-lg`}
      >
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-3">
            <span className={`text-lg font-semibold ${directionStyles.text}`}>
              {synthesis.setup_type}
            </span>
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${directionStyles.text}`}>
              {synthesis.bias.charAt(0).toUpperCase() + synthesis.bias.slice(1)}
            </span>
            <span
              className={`border rounded px-2 py-0.5 text-xs font-medium ${confidenceBadge.base} ${confidenceBadge.text}`}
            >
              {confidenceBadge.label} Confidence
            </span>
          </div>
          <span className="text-xs text-gray-500">
            Generated: {formatTimeAgo(synthesis.generated_at)}
          </span>
        </div>
      </div>

      {/* Warning for parse errors */}
      {synthesis.parse_error && (
        <div className="border-b border-yellow-700/40 bg-yellow-950/30 px-4 py-2">
          <p className="text-xs text-yellow-400">
            Warning: Analysis may be incomplete due to parsing issues. Use with caution.
          </p>
        </div>
      )}

      {/* Main content */}
      <div className="px-4 py-3 space-y-3">
        {/* Summary */}
        <div>
          <p className="text-sm text-gray-200 leading-relaxed">{synthesis.summary}</p>
        </div>

        {/* Confluence and conflicts */}
        <div className="grid grid-cols-1 gap-2 text-sm">
          <div>
            <p className="text-xs text-gray-500 font-semibold uppercase tracking-wider mb-1">
              Confluence
            </p>
            <p className="text-gray-300">{synthesis.signal_confluence}</p>
          </div>
          {synthesis.signal_conflicts && (
            <div>
              <p className="text-xs text-gray-500 font-semibold uppercase tracking-wider mb-1">
                Conflicts
              </p>
              <p className="text-gray-300">{synthesis.signal_conflicts}</p>
            </div>
          )}
        </div>

        {/* Entry/Stop/Target levels */}
        <div className="pt-2 border-t border-gray-700/30">
          <div className="grid grid-cols-3 gap-3 text-center">
            {synthesis.entry != null && (
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">Entry</p>
                <p className="font-mono text-lg font-semibold text-gray-200">
                  ${synthesis.entry.toFixed(2)}
                </p>
              </div>
            )}
            {synthesis.stop != null && (
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">Stop</p>
                <p className="font-mono text-lg font-semibold text-red-400">
                  ${synthesis.stop.toFixed(2)}
                </p>
              </div>
            )}
            {synthesis.target != null && (
              <div>
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">Target</p>
                <p className="font-mono text-lg font-semibold text-green-400">
                  ${synthesis.target.toFixed(2)}
                </p>
              </div>
            )}
          </div>

          {/* Risk/Reward ratio */}
          {synthesis.risk_reward != null && (
            <div className="mt-2 flex justify-center">
              <div className="px-3 py-1.5 rounded bg-gray-800/50 text-center">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-0.5">Risk/Reward</p>
                <p className="font-mono text-base font-semibold text-gray-200">
                  {synthesis.risk_reward.toFixed(2)}x
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Key risk */}
        {synthesis.key_risk && (
          <div className="pt-2 border-t border-gray-700/30 bg-gray-800/20 rounded px-3 py-2">
            <p className="text-xs text-gray-500 font-semibold uppercase tracking-wider mb-1">
              Key Risk
            </p>
            <p className="text-sm text-gray-300">{synthesis.key_risk}</p>
          </div>
        )}
      </div>
    </div>
  );
}
