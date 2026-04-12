import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { watchlistApi } from '../../api/watchlists';
import type { Watchlist } from '../../types';
import { LoadingSpinner } from '../shared/LoadingSpinner';
import { AddSymbolInput } from './AddSymbolInput';
import { SAImportButton } from './SAImportButton';

interface Props {
  watchlist: Watchlist;
}

function GradeBadge({ grade }: { grade: string | null }) {
  if (!grade) return <span className="text-gray-600">—</span>;
  const color = grade.startsWith('A')
    ? 'text-green-400 bg-green-950/50 border-green-800'
    : grade.startsWith('B')
      ? 'text-blue-400 bg-blue-950/50 border-blue-800'
      : grade.startsWith('C')
        ? 'text-yellow-400 bg-yellow-950/50 border-yellow-800'
        : 'text-red-400 bg-red-950/50 border-red-800';
  return (
    <span className={`inline-block px-1.5 py-0.5 rounded text-xs font-semibold border ${color}`}>
      {grade}
    </span>
  );
}

export function WatchlistDetail({ watchlist }: Props) {
  const queryClient = useQueryClient();

  const { data: items = [], isLoading } = useQuery({
    queryKey: ['watchlist', watchlist.id, 'items'],
    queryFn: () => watchlistApi.getItems(watchlist.id),
  });

  const removeMutation = useMutation({
    mutationFn: (ticker: string) => watchlistApi.removeSymbol(watchlist.id, ticker),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['watchlist', watchlist.id, 'items'] });
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] });
    },
  });

  return (
    <div className="flex flex-col gap-4">
      {/* Detail header */}
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-semibold text-white">{watchlist.name}</h2>
          {watchlist.is_default && (
            <span className="px-1.5 py-0.5 rounded text-xs font-semibold bg-blue-900/50 border border-blue-700 text-blue-300">
              active
            </span>
          )}
          <span className="text-xs text-gray-500">{watchlist.item_count} symbols</span>
        </div>
        <SAImportButton watchlistId={watchlist.id} />
      </div>

      {/* Add symbol */}
      <AddSymbolInput watchlistId={watchlist.id} />

      {/* Items table */}
      {isLoading ? (
        <div className="flex justify-center py-8">
          <LoadingSpinner size="lg" />
        </div>
      ) : items.length === 0 ? (
        <div className="text-center py-10 text-gray-500 text-sm">
          No symbols yet. Add a ticker above or import an SA spreadsheet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800 text-left text-xs text-gray-500 uppercase tracking-wide">
                <th className="pb-2 pr-4">Symbol</th>
                <th className="pb-2 pr-4">Quant</th>
                <th className="pb-2 pr-4">Momentum</th>
                <th className="pb-2 pr-4">Valuation</th>
                <th className="pb-2 pr-4">Growth</th>
                <th className="pb-2 w-6"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/50">
              {items.map((item) => (
                <tr key={item.id} className="hover:bg-gray-800/30 transition-colors">
                  <td className="py-2 pr-4 font-mono font-semibold text-white">
                    {item.ticker}
                    {item.name && (
                      <span className="ml-2 text-xs text-gray-500 font-normal">{item.name}</span>
                    )}
                  </td>
                  <td className="py-2 pr-4 text-gray-300">
                    {item.quant_score != null ? item.quant_score.toFixed(2) : '—'}
                  </td>
                  <td className="py-2 pr-4">
                    <GradeBadge grade={item.momentum_grade} />
                  </td>
                  <td className="py-2 pr-4">
                    <GradeBadge grade={item.valuation_grade} />
                  </td>
                  <td className="py-2 pr-4">
                    <GradeBadge grade={item.growth_grade} />
                  </td>
                  <td className="py-2">
                    <button
                      onClick={() => removeMutation.mutate(item.ticker)}
                      disabled={removeMutation.isPending}
                      className="text-gray-600 hover:text-red-400 transition-colors text-base leading-none"
                      title={`Remove ${item.ticker}`}
                    >
                      ✕
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
