import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { scannerApi } from '../api/scanner'
import { watchlistApi } from '../api/watchlists'
import { useScannerStore } from '../stores/scannerStore'
import { ProfileFilterTabs } from '../components/scanner/ProfileFilterTabs'
import { ResultsTable } from '../components/scanner/ResultsTable'
import { LoadingSpinner } from '../components/shared/LoadingSpinner'
import { WatchlistSwitcher } from '../components/watchlist/WatchlistSwitcher'

const SCAN_POLL_INTERVAL_MS = 5_000
const SCAN_TIMEOUT_MS = 120_000

function formatTimeAgo(d: Date | null): string {
  if (!d) return '—'
  const secs = Math.round((Date.now() - d.getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

export function ScannerPage() {
  const queryClient = useQueryClient()
  const {
    activeProfile, isScanning, lastFetched, activeRunId,
    setActiveProfile, setIsScanning, setActiveRunId, setScanStartTime, setLastFetched,
  } = useScannerStore()
  const [scanError, setScanError] = useState<string | null>(null)

  // Mirror the WatchlistSwitcher's cache key so we react when the active watchlist changes
  const { data: watchlists = [] } = useQuery({
    queryKey: ['watchlists'],
    queryFn: () => watchlistApi.getAll(),
    staleTime: 60_000,
  })
  const activeWatchlistId = watchlists.find((w) => w.is_default)?.id ?? null

  const { data: results = [], isLoading, isError } = useQuery({
    queryKey: ['scanner', 'results', activeProfile, activeWatchlistId],
    queryFn: () => scannerApi.getResults(activeProfile, activeWatchlistId),
    staleTime: 60_000,
    refetchInterval: false,
    select: (data) => data,
  })

  // Poll run status while a scan is active
  const { data: runStatus } = useQuery({
    queryKey: ['scanner', 'run', activeRunId],
    queryFn: () => scannerApi.getRunStatus(activeRunId!),
    enabled: isScanning && activeRunId != null,
    refetchInterval: isScanning && activeRunId != null ? SCAN_POLL_INTERVAL_MS : false,
  })

  // React to run status changes
  useEffect(() => {
    if (!runStatus || !isScanning) return

    if (runStatus.status === 'completed') {
      setIsScanning(false)
      setActiveRunId(null)
      if (runStatus.symbols_scored === 0) {
        setScanError(
          `Scan completed but found no results (${runStatus.symbols_scanned} symbols checked). ` +
          'Make sure OHLCV data has been ingested for your watchlist symbols.'
        )
      } else {
        setScanError(null)
      }
      // Fetch fresh results now that scan is done
      void queryClient.invalidateQueries({ queryKey: ['scanner', 'results'] })
    } else if (runStatus.status === 'failed') {
      setIsScanning(false)
      setActiveRunId(null)
      setScanError(
        runStatus.error_message
          ? `Scan failed: ${runStatus.error_message}`
          : 'Scan failed — check backend logs for details.'
      )
    }
  }, [runStatus, isScanning, setIsScanning, setActiveRunId, queryClient])

  // Track last fetched time
  useEffect(() => {
    if (results.length > 0) {
      setLastFetched(new Date())
    }
  }, [results, setLastFetched])

  // Safety-net timeout: give up after SCAN_TIMEOUT_MS regardless of status
  useEffect(() => {
    if (!isScanning) return
    const timer = setTimeout(() => {
      setIsScanning(false)
      setActiveRunId(null)
      setScanError('Scan timed out — background task may have failed. Check backend logs.')
    }, SCAN_TIMEOUT_MS)
    return () => clearTimeout(timer)
  }, [isScanning, setIsScanning, setActiveRunId])

  const handleRunScan = useCallback(async () => {
    setScanError(null)
    setIsScanning(true)
    setScanStartTime(new Date())
    try {
      const runResp = await scannerApi.runScan(activeWatchlistId)
      setActiveRunId(runResp.run_id)
    } catch (err) {
      setIsScanning(false)
      setActiveRunId(null)
      setScanError(err instanceof Error ? err.message : 'Scan failed')
    }
  }, [setIsScanning, setScanStartTime, setActiveRunId, activeWatchlistId])

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3">
        <div className="max-w-screen-xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold text-white tracking-tight">Stonky</h1>
            <nav className="flex items-center gap-3 text-sm">
              <span className="text-white font-medium">Scanner</span>
              <span className="text-gray-700">|</span>
              <Link
                to="/watchlists"
                className="text-gray-400 hover:text-white transition-colors"
              >
                Watchlists
              </Link>
            </nav>
          </div>
          <WatchlistSwitcher />
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500">
              {isLoading ? 'Fetching…' : lastFetched ? `Last refreshed: ${formatTimeAgo(lastFetched)}` : 'Not yet scanned'}
            </span>
            <button
              onClick={() => { void handleRunScan() }}
              disabled={isScanning}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-60 text-xs font-semibold text-white transition-colors"
            >
              {isScanning && <LoadingSpinner size="sm" />}
              {isScanning ? 'Scanning…' : 'Run Scan'}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-screen-xl mx-auto px-6 py-4 space-y-4">
        {/* Scan error banner */}
        {scanError && (
          <div className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-2 text-sm text-red-400">
            {scanError}
          </div>
        )}

        {/* Profile filter tabs */}
        <ProfileFilterTabs
          active={activeProfile}
          onChange={(p) => {
            setActiveProfile(p)
            void queryClient.invalidateQueries({ queryKey: ['scanner', 'results', p] })
          }}
        />

        {/* Table */}
        {isLoading ? (
          <div className="flex justify-center py-16">
            <LoadingSpinner size="lg" />
          </div>
        ) : isError ? (
          <div className="rounded-lg border border-red-800 bg-red-950/40 p-4 text-sm text-red-400">
            Failed to load results. Is the backend running?
          </div>
        ) : (
          <ResultsTable results={results} activeProfile={activeProfile} hasScanned={lastFetched != null} />
        )}
      </main>
    </div>
  )
}
