import { useCallback, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { scannerApi } from '../api/scanner'
import { useScannerStore } from '../stores/scannerStore'
import { ProfileFilterTabs } from '../components/scanner/ProfileFilterTabs'
import { ResultsTable } from '../components/scanner/ResultsTable'
import { LoadingSpinner } from '../components/shared/LoadingSpinner'

function formatTimeAgo(d: Date | null): string {
  if (!d) return '—'
  const secs = Math.round((Date.now() - d.getTime()) / 1000)
  if (secs < 60) return `${secs}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}

export function ScannerPage() {
  const queryClient = useQueryClient()
  const { activeProfile, isScanning, lastFetched, setActiveProfile, setIsScanning, setScanStartTime, setLastFetched } =
    useScannerStore()

  const { data: results = [], isLoading, isError } = useQuery({
    queryKey: ['scanner', 'results', activeProfile],
    queryFn: () => scannerApi.getResults(activeProfile),
    staleTime: 60_000,
    refetchInterval: isScanning ? 3_000 : false,
    select: (data) => data, // keep as-is; already sorted by rank from backend
  })

  // Track last fetched time
  useEffect(() => {
    if (results.length > 0) {
      setLastFetched(new Date())
    }
  }, [results, setLastFetched])

  // Stop polling when scan results are fresh (result timestamp > scan start)
  useEffect(() => {
    if (!isScanning) return
    if (results.length > 0) {
      setIsScanning(false)
    }
  }, [isScanning, results, setIsScanning])

  const handleRunScan = useCallback(async () => {
    setIsScanning(true)
    setScanStartTime(new Date())
    try {
      await scannerApi.runScan()
      // Invalidate immediately — the refetchInterval will pick up fresh data
      await queryClient.invalidateQueries({ queryKey: ['scanner', 'results'] })
    } catch {
      setIsScanning(false)
    }
  }, [queryClient, setIsScanning, setScanStartTime])

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3">
        <div className="max-w-screen-xl mx-auto flex items-center justify-between gap-4">
          <h1 className="text-lg font-bold text-white tracking-tight">Stonky</h1>
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
          <ResultsTable results={results} />
        )}
      </main>
    </div>
  )
}
