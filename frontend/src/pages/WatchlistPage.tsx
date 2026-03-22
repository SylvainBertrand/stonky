import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { watchlistApi } from '../api/watchlists'
import { useWatchlistStore } from '../stores/watchlistStore'
import { WatchlistList } from '../components/watchlist/WatchlistList'
import { WatchlistDetail } from '../components/watchlist/WatchlistDetail'
import { LoadingSpinner } from '../components/shared/LoadingSpinner'

export function WatchlistPage() {
  const { selectedWatchlistId, setSelectedWatchlistId } = useWatchlistStore()

  const { data: watchlists = [], isLoading } = useQuery({
    queryKey: ['watchlists'],
    queryFn: () => watchlistApi.getAll(),
  })

  const { data: activeWatchlist } = useQuery({
    queryKey: ['watchlist', 'active'],
    queryFn: () => watchlistApi.getActive(),
  })

  // On first load, default selectedWatchlistId to the active watchlist
  useEffect(() => {
    if (selectedWatchlistId === null && activeWatchlist) {
      setSelectedWatchlistId(activeWatchlist.id)
    } else if (selectedWatchlistId === null && watchlists.length > 0) {
      setSelectedWatchlistId(watchlists[0].id)
    }
  }, [activeWatchlist, watchlists, selectedWatchlistId, setSelectedWatchlistId])

  const selectedWatchlist =
    watchlists.find((w) => w.id === selectedWatchlistId) ?? watchlists[0] ?? null

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3">
        <div className="max-w-screen-xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold text-white tracking-tight">Stonky</h1>
            <nav className="flex items-center gap-3 text-sm">
              <Link
                to="/"
                className="text-gray-400 hover:text-white transition-colors"
              >
                Scanner
              </Link>
              <span className="text-gray-700">|</span>
              <span className="text-white font-medium">Watchlists</span>
              <span className="text-gray-700">|</span>
              <Link
                to="/backtest"
                className="text-gray-400 hover:text-white transition-colors"
              >
                Backtest
              </Link>
              <span className="text-gray-700">|</span>
              <Link
                to="/market"
                className="text-gray-400 hover:text-white transition-colors"
              >
                Market
              </Link>
            </nav>
          </div>
        </div>
      </header>

      <main className="max-w-screen-xl mx-auto px-6 py-6">
        {isLoading ? (
          <div className="flex justify-center py-16">
            <LoadingSpinner size="lg" />
          </div>
        ) : (
          <div className="flex gap-6">
            {/* Left panel: watchlist list */}
            <div className="w-56 shrink-0">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                Watchlists
              </h2>
              <WatchlistList
                watchlists={watchlists}
                selectedId={selectedWatchlist?.id ?? null}
                onSelect={(id) => setSelectedWatchlistId(id)}
              />
            </div>

            {/* Right panel: watchlist detail */}
            <div className="flex-1 min-w-0">
              {selectedWatchlist ? (
                <WatchlistDetail watchlist={selectedWatchlist} />
              ) : (
                <div className="text-center py-16 text-gray-500 text-sm">
                  No watchlists yet. Create one to get started.
                </div>
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
