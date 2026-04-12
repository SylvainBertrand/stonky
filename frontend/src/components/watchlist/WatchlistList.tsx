import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { watchlistApi } from '../../api/watchlists';
import { useWatchlistStore } from '../../stores/watchlistStore';
import type { Watchlist } from '../../types';

interface Props {
  watchlists: Watchlist[];
  selectedId: number | null;
  onSelect: (id: number) => void;
}

export function WatchlistList({ watchlists, selectedId, onSelect }: Props) {
  const [showNewInput, setShowNewInput] = useState(false);
  const [newName, setNewName] = useState('');
  const queryClient = useQueryClient();
  const { setSelectedWatchlistId } = useWatchlistStore();

  const createMutation = useMutation({
    mutationFn: (name: string) => watchlistApi.create(name),
    onSuccess: (created) => {
      setNewName('');
      setShowNewInput(false);
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      onSelect(created.id);
    },
  });

  const setActiveMutation = useMutation({
    mutationFn: (id: number) => watchlistApi.setActive(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      void queryClient.invalidateQueries({ queryKey: ['watchlist', 'active'] });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => watchlistApi.delete(id),
    onSuccess: (_, deletedId) => {
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] });
      void queryClient.invalidateQueries({ queryKey: ['watchlist', 'active'] });
      if (selectedId === deletedId) {
        const remaining = watchlists.find((w) => w.id !== deletedId);
        const nextId = remaining?.id ?? null;
        setSelectedWatchlistId(nextId);
        onSelect(nextId ?? 0);
      }
    },
  });

  const handleCreateSubmit = () => {
    const name = newName.trim();
    if (!name) return;
    createMutation.mutate(name);
  };

  return (
    <div className="flex flex-col gap-1">
      {watchlists.map((wl) => (
        <div
          key={wl.id}
          onClick={() => onSelect(wl.id)}
          className={`flex items-center justify-between px-3 py-2 rounded cursor-pointer transition-colors ${
            selectedId === wl.id
              ? 'bg-gray-700/60 text-white'
              : 'hover:bg-gray-800/60 text-gray-300'
          }`}
        >
          <div className="flex items-center gap-2 min-w-0">
            {wl.is_default && (
              <span className="text-blue-400 shrink-0" title="Active watchlist">
                ●
              </span>
            )}
            <span className="truncate text-sm font-medium">{wl.name}</span>
            <span className="text-xs text-gray-500 shrink-0">{wl.item_count}</span>
          </div>
          <div className="flex items-center gap-1 shrink-0 ml-2">
            {!wl.is_default && (
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setActiveMutation.mutate(wl.id);
                }}
                disabled={setActiveMutation.isPending}
                className="px-2 py-0.5 rounded text-xs text-gray-400 hover:text-blue-300 hover:bg-gray-700 transition-colors"
                title="Set as active"
              >
                Set Active
              </button>
            )}
            <button
              onClick={(e) => {
                e.stopPropagation();
                if (watchlists.length <= 1) return;
                if (window.confirm(`Delete "${wl.name}"?`)) {
                  deleteMutation.mutate(wl.id);
                }
              }}
              disabled={watchlists.length <= 1 || deleteMutation.isPending}
              className="px-1.5 py-0.5 rounded text-xs text-gray-600 hover:text-red-400 disabled:opacity-30 transition-colors"
              title={
                watchlists.length <= 1 ? 'Cannot delete the only watchlist' : `Delete "${wl.name}"`
              }
            >
              ✕
            </button>
          </div>
        </div>
      ))}

      {/* New watchlist input */}
      {showNewInput ? (
        <div className="flex gap-1.5 mt-1">
          <input
            autoFocus
            type="text"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreateSubmit();
              if (e.key === 'Escape') {
                setShowNewInput(false);
                setNewName('');
              }
            }}
            onBlur={() => {
              if (!newName.trim()) {
                setShowNewInput(false);
              }
            }}
            placeholder="Watchlist name…"
            className="flex-1 px-2 py-1 rounded bg-gray-800 border border-gray-700 text-xs text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={handleCreateSubmit}
            disabled={createMutation.isPending || !newName.trim()}
            className="px-2 py-1 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-xs text-white"
          >
            {createMutation.isPending ? '…' : 'Add'}
          </button>
        </div>
      ) : (
        <button
          onClick={() => setShowNewInput(true)}
          className="mt-1 px-3 py-1.5 rounded text-xs text-gray-400 hover:text-white hover:bg-gray-800 border border-dashed border-gray-700 transition-colors text-left"
        >
          + New Watchlist
        </button>
      )}
    </div>
  );
}
