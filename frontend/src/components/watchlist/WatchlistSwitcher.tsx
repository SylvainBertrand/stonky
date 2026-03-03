import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { watchlistApi } from '../../api/watchlists'
import { useWatchlistStore } from '../../stores/watchlistStore'

export function WatchlistSwitcher() {
  const [open, setOpen] = useState(false)
  const [switchedTo, setSwitchedTo] = useState<string | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const queryClient = useQueryClient()
  const { setSelectedWatchlistId } = useWatchlistStore()

  const { data: watchlists = [] } = useQuery({
    queryKey: ['watchlists'],
    queryFn: () => watchlistApi.getAll(),
  })

  const active = watchlists.find((w) => w.is_default) ?? null

  const setActiveMutation = useMutation({
    mutationFn: (id: number) => watchlistApi.setActive(id),
    onSuccess: (wl) => {
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] })
      void queryClient.invalidateQueries({ queryKey: ['watchlist', 'active'] })
      void queryClient.invalidateQueries({ queryKey: ['scanner', 'results'] })
      setSelectedWatchlistId(wl.id)
      setSwitchedTo(wl.name)
      setOpen(false)
      setTimeout(() => setSwitchedTo(null), 4000)
    },
  })

  if (watchlists.length === 0) return null

  return (
    <div className="relative" ref={containerRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-gray-800 hover:bg-gray-700 border border-gray-700 text-sm text-gray-200 transition-colors"
      >
        <span className="text-blue-400 text-xs">●</span>
        <span className="max-w-[140px] truncate">{active?.name ?? 'No active watchlist'}</span>
        <span className="text-gray-500 text-xs">▾</span>
      </button>

      {open && (
        <div className="absolute top-full left-0 mt-1 z-50 min-w-[180px] rounded-lg border border-gray-700 bg-gray-900 shadow-xl py-1">
          {watchlists.map((wl) => (
            <button
              key={wl.id}
              onClick={() => {
                if (!wl.is_default) {
                  setActiveMutation.mutate(wl.id)
                } else {
                  setOpen(false)
                }
              }}
              className={`w-full text-left px-3 py-1.5 text-sm transition-colors flex items-center gap-2 ${
                wl.is_default
                  ? 'text-white bg-gray-800/50'
                  : 'text-gray-300 hover:bg-gray-800 hover:text-white'
              }`}
            >
              {wl.is_default && <span className="text-blue-400 text-xs shrink-0">●</span>}
              <span className="truncate">{wl.name}</span>
              <span className="text-gray-600 text-xs ml-auto shrink-0">{wl.item_count}</span>
            </button>
          ))}
        </div>
      )}

      {switchedTo && (
        <div className="absolute top-full left-0 mt-1 z-50 px-3 py-1.5 rounded bg-gray-800 border border-gray-700 text-xs text-gray-300 whitespace-nowrap shadow-lg">
          Run Scan to see results for <span className="text-white font-medium">{switchedTo}</span>
        </div>
      )}
    </div>
  )
}
