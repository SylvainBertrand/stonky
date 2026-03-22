import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { scannerApi, patternsApi, forecastsApi, synthesisApi, pipelineApi } from '../api/scanner'
import type { PipelineStatus } from '../api/scanner'
import { watchlistApi } from '../api/watchlists'
import { useScannerStore } from '../stores/scannerStore'
import type { ForecastData, SynthesisData } from '../types'
import { ProfileFilterTabs } from '../components/scanner/ProfileFilterTabs'
import { ResultsTable } from '../components/scanner/ResultsTable'
import { LoadingSpinner } from '../components/shared/LoadingSpinner'
import { WatchlistSwitcher } from '../components/watchlist/WatchlistSwitcher'
import { MarketRegimeStrip } from '../components/market/MarketRegimeStrip'

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
  const [isYoloScanning, setIsYoloScanning] = useState(false)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [isForecastScanning, setIsForecastScanning] = useState(false)
  const [isSynthesisScanning, setIsSynthesisScanning] = useState(false)
  const [isPipelineRunning, setIsPipelineRunning] = useState(false)
  const [pipelineProgress, setPipelineProgress] = useState<PipelineStatus | null>(null)
  const [forecasts, setForecasts] = useState<Record<string, ForecastData>>({})
  const [syntheses, setSyntheses] = useState<Record<string, SynthesisData>>({})

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

  // Fetch forecasts for scanner results
  useEffect(() => {
    if (results.length === 0) return
    const fetchForecasts = async () => {
      const map: Record<string, ForecastData> = {}
      await Promise.all(
        results.map(async (r) => {
          try {
            const fc = await forecastsApi.getForecast(r.symbol)
            if (fc) map[r.symbol] = fc
          } catch { /* forecast not available */ }
        })
      )
      setForecasts(map)
    }
    void fetchForecasts()
  }, [results])

  // Fetch syntheses for scanner results
  useEffect(() => {
    if (results.length === 0) return
    const fetchSyntheses = async () => {
      const map: Record<string, SynthesisData> = {}
      await Promise.all(
        results.map(async (r) => {
          try {
            const syn = await synthesisApi.getSynthesis(r.symbol)
            if (syn) map[r.symbol] = syn
          } catch { /* synthesis not available */ }
        })
      )
      setSyntheses(map)
    }
    void fetchSyntheses()
  }, [results])

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

  const handleRefreshData = useCallback(async () => {
    if (!activeWatchlistId) return
    setIsRefreshing(true)
    setScanError(null)
    try {
      await watchlistApi.refreshData(activeWatchlistId)
    } catch (err) {
      setScanError(err instanceof Error ? err.message : 'Data refresh failed')
    } finally {
      setIsRefreshing(false)
    }
  }, [activeWatchlistId])

  const handleYoloScan = useCallback(async () => {
    setIsYoloScanning(true)
    setScanError(null)
    try {
      await patternsApi.triggerScan(activeWatchlistId)
      // Poll status until complete
      const poll = async () => {
        for (let i = 0; i < 60; i++) { // max 5 minutes (60 * 5s)
          await new Promise((r) => setTimeout(r, 5000))
          try {
            const status = await patternsApi.getScanStatus()
            if (status.status === 'completed') {
              void queryClient.invalidateQueries({ queryKey: ['scanner', 'results'] })
              setIsYoloScanning(false)
              return
            }
            if (status.status === 'failed') {
              setScanError('Chart pattern scan failed — check backend logs.')
              setIsYoloScanning(false)
              return
            }
          } catch {
            // Status endpoint may not exist yet if scan just started
          }
        }
        setScanError('Chart pattern scan timed out.')
        setIsYoloScanning(false)
      }
      void poll()
    } catch (err) {
      setIsYoloScanning(false)
      setScanError(err instanceof Error ? err.message : 'Chart pattern scan failed')
    }
  }, [activeWatchlistId, queryClient])

  const handleForecastScan = useCallback(async () => {
    setIsForecastScanning(true)
    setScanError(null)
    try {
      await forecastsApi.triggerScan(activeWatchlistId)
      const poll = async () => {
        for (let i = 0; i < 120; i++) {
          await new Promise((r) => setTimeout(r, 5000))
          try {
            const status = await forecastsApi.getScanStatus()
            if (status.status === 'completed') {
              void queryClient.invalidateQueries({ queryKey: ['scanner', 'results'] })
              setIsForecastScanning(false)
              return
            }
            if (status.status === 'failed') {
              setScanError('Forecast scan failed — check backend logs.')
              setIsForecastScanning(false)
              return
            }
          } catch {
            // Status endpoint may not exist yet if scan just started
          }
        }
        setScanError('Forecast scan timed out.')
        setIsForecastScanning(false)
      }
      void poll()
    } catch (err) {
      setIsForecastScanning(false)
      setScanError(err instanceof Error ? err.message : 'Forecast scan failed')
    }
  }, [activeWatchlistId, queryClient])

  const handleSynthesisScan = useCallback(async () => {
    setIsSynthesisScanning(true)
    setScanError(null)
    try {
      await synthesisApi.triggerScan(activeWatchlistId)
      const poll = async () => {
        for (let i = 0; i < 120; i++) {
          await new Promise((r) => setTimeout(r, 5000))
          try {
            const status = await synthesisApi.getScanStatus()
            if (status.status === 'completed') {
              void queryClient.invalidateQueries({ queryKey: ['scanner', 'results'] })
              setIsSynthesisScanning(false)
              return
            }
            if (status.status === 'failed') {
              setScanError('Synthesis scan failed — check backend logs.')
              setIsSynthesisScanning(false)
              return
            }
          } catch {
            // Status endpoint may not exist yet if scan just started
          }
        }
        setScanError('Synthesis scan timed out.')
        setIsSynthesisScanning(false)
      }
      void poll()
    } catch (err) {
      setIsSynthesisScanning(false)
      setScanError(err instanceof Error ? err.message : 'Synthesis scan failed')
    }
  }, [activeWatchlistId, queryClient])

  const handlePipelineRun = useCallback(async () => {
    setIsPipelineRunning(true)
    setScanError(null)
    setPipelineProgress(null)
    try {
      const resp = await pipelineApi.run(activeWatchlistId)
      if (resp.status === 'already_running') {
        setScanError('Pipeline is already running.')
        setIsPipelineRunning(false)
        return
      }
    } catch (err) {
      setIsPipelineRunning(false)
      setScanError(err instanceof Error ? err.message : 'Pipeline failed to start')
    }
  }, [activeWatchlistId])

  // Poll pipeline status while running
  useEffect(() => {
    if (!isPipelineRunning) return
    let cancelled = false
    const poll = async () => {
      while (!cancelled) {
        await new Promise((r) => setTimeout(r, 5000))
        if (cancelled) break
        try {
          const status = await pipelineApi.getStatus()
          setPipelineProgress(status)
          if (status.status === 'completed' || status.status === 'failed') {
            setIsPipelineRunning(false)
            if (status.status === 'failed') {
              setScanError('Pipeline failed — check backend logs.')
            }
            void queryClient.invalidateQueries({ queryKey: ['scanner', 'results'] })
            break
          }
        } catch {
          // status endpoint may not be ready yet
        }
      }
    }
    void poll()
    return () => { cancelled = true }
  }, [isPipelineRunning, queryClient])

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
          <WatchlistSwitcher />
          <div className="flex items-center gap-3">
            <button
              onClick={() => { void handleRefreshData() }}
              disabled={isRefreshing || !activeWatchlistId}
              className="flex items-center gap-1.5 px-2.5 py-1.5 rounded border border-gray-700 hover:border-gray-500 disabled:opacity-50 text-xs text-gray-400 hover:text-white transition-colors"
              title="Fetch latest OHLCV data from yfinance"
            >
              {isRefreshing && <LoadingSpinner size="sm" />}
              {isRefreshing ? 'Refreshing…' : 'Refresh Data'}
            </button>
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
            <button
              onClick={() => { void handleYoloScan() }}
              disabled={isYoloScanning || isScanning}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-purple-700 hover:bg-purple-600 disabled:opacity-60 text-xs font-semibold text-white transition-colors"
            >
              {isYoloScanning && <LoadingSpinner size="sm" />}
              {isYoloScanning ? 'Detecting…' : 'Scan Chart Patterns'}
            </button>
            <button
              onClick={() => { void handleForecastScan() }}
              disabled={isForecastScanning || isScanning}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-teal-700 hover:bg-teal-600 disabled:opacity-60 text-xs font-semibold text-white transition-colors"
            >
              {isForecastScanning && <LoadingSpinner size="sm" />}
              {isForecastScanning ? 'Forecasting…' : 'Run Forecasts'}
            </button>
            <button
              onClick={() => { void handleSynthesisScan() }}
              disabled={isSynthesisScanning || isScanning || isPipelineRunning}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-amber-700 hover:bg-amber-600 disabled:opacity-60 text-xs font-semibold text-white transition-colors"
            >
              {isSynthesisScanning && <LoadingSpinner size="sm" />}
              {isSynthesisScanning ? 'Analyzing…' : 'Run Analysis'}
            </button>
            <button
              onClick={() => { void handlePipelineRun() }}
              disabled={isPipelineRunning || isScanning}
              className="flex items-center gap-2 px-3 py-1.5 rounded bg-green-700 hover:bg-green-600 disabled:opacity-60 text-xs font-semibold text-white transition-colors"
              title="Run full pipeline: YOLO + Chronos + Synthesis for all symbols"
            >
              {isPipelineRunning && <LoadingSpinner size="sm" />}
              {isPipelineRunning ? 'Running…' : 'Run All'}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-screen-xl mx-auto px-6 py-4 space-y-4">
        <MarketRegimeStrip />

        {/* Pipeline progress banner */}
        {isPipelineRunning && pipelineProgress && pipelineProgress.status === 'running' && (
          <div className="rounded-lg border border-green-800 bg-green-950/30 px-4 py-2 text-sm text-green-400 flex items-center gap-3">
            <LoadingSpinner size="sm" />
            <span>
              Running pipeline… {pipelineProgress.symbols_completed}/{pipelineProgress.symbols_total} symbols complete
              {pipelineProgress.symbols_failed > 0 && ` (${pipelineProgress.symbols_failed} failed)`}
            </span>
            {pipelineProgress.current_symbols.length > 0 && (
              <span className="text-green-600 text-xs">
                Currently: {pipelineProgress.current_symbols.join(', ')}
              </span>
            )}
            {pipelineProgress.estimated_remaining_s != null && (
              <span className="text-green-600 text-xs ml-auto">
                ~{Math.round(pipelineProgress.estimated_remaining_s)}s remaining
              </span>
            )}
          </div>
        )}

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
          <ResultsTable results={results} activeProfile={activeProfile} hasScanned={lastFetched != null} forecasts={forecasts} syntheses={syntheses} />
        )}
      </main>
    </div>
  )
}
