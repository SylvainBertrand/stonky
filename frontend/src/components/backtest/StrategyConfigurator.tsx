import { useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'
import { backtestApi } from '../../api/backtests'
import { useBacktestStore } from '../../stores/backtestStore'
import type { StrategyType } from '../../types'
import { LoadingSpinner } from '../shared/LoadingSpinner'

// Strategy parameter metadata
const STRATEGY_PARAMS: Record<StrategyType, Array<{ name: string; default: number; min: number; max: number }>> = {
  ema_crossover: [
    { name: 'fast', default: 21, min: 2, max: 100 },
    { name: 'slow', default: 50, min: 2, max: 200 },
  ],
  rsi_threshold: [
    { name: 'oversold', default: 30, min: 10, max: 50 },
    { name: 'overbought', default: 70, min: 50, max: 90 },
  ],
  macd_cross: [
    { name: 'fast', default: 12, min: 5, max: 50 },
    { name: 'slow', default: 26, min: 5, max: 100 },
    { name: 'signal', default: 9, min: 3, max: 30 },
  ],
  supertrend: [
    { name: 'atr_period', default: 10, min: 5, max: 50 },
    { name: 'multiplier', default: 3.0, min: 1.0, max: 10.0 },
  ],
  momentum_breakout: [
    { name: 'rsi_min', default: 50, min: 30, max: 70 },
    { name: 'rsi_max', default: 70, min: 50, max: 90 },
    { name: 'adx_min', default: 20, min: 10, max: 40 },
    { name: 'volume_multiplier', default: 1.5, min: 0.5, max: 5.0 },
  ],
  trend_following: [
    { name: 'adx_min', default: 25, min: 10, max: 40 },
    { name: 'rsi_pullback_min', default: 40, min: 20, max: 50 },
    { name: 'rsi_pullback_max', default: 50, min: 40, max: 70 },
  ],
  mean_reversion: [
    { name: 'rsi_max', default: 30, min: 15, max: 45 },
    { name: 'stoch_k_max', default: 20, min: 5, max: 40 },
  ],
  harmonic_setup: [
    { name: 'min_pattern_score', default: 0.6, min: 0.1, max: 1.0 },
  ],
  yolo_pattern: [
    { name: 'min_confidence', default: 0.7, min: 0.1, max: 1.0 },
  ],
  custom: [],
}

export function StrategyConfigurator() {
  const {
    strategyType,
    symbol,
    timeframe,
    startDate,
    endDate,
    initialCapital,
    parameters,
    isRunning,
    error,
    setStrategyType,
    setSymbol,
    setTimeframe,
    setStartDate,
    setEndDate,
    setInitialCapital,
    setParameter,
    setResult,
    setIsRunning,
    setError,
  } = useBacktestStore()

  const runMutation = useMutation({
    mutationFn: async () => {
      setIsRunning(true)
      setError(null)
      try {
        const result = await backtestApi.run({
          symbol,
          timeframe: timeframe === 'Daily' ? '1d' : '1w',
          start_date: startDate,
          end_date: endDate,
          initial_capital: initialCapital,
          strategy_type: strategyType,
          parameters,
        })
        setResult(result)
        return result
      } catch (err) {
        const msg = err instanceof Error ? err.message : 'Backtest failed'
        setError(msg)
        throw err
      } finally {
        setIsRunning(false)
      }
    },
  })

  const handleRun = useCallback(async () => {
    if (!symbol || !startDate || !endDate) {
      setError('Please fill in all required fields')
      return
    }
    await runMutation.mutateAsync()
  }, [symbol, startDate, endDate, runMutation, setError])

  const strategyParams = STRATEGY_PARAMS[strategyType] || []

  // Initialize parameters if not already set
  if (Object.keys(parameters).length === 0 && strategyParams.length > 0) {
    const initialParams: Record<string, unknown> = {}
    for (const param of strategyParams) {
      initialParams[param.name] = param.default
    }
    // Use a quick update without triggering re-renders
    Object.entries(initialParams).forEach(([key, value]) => {
      if (!(key in parameters)) {
        setParameter(key, value)
      }
    })
  }

  return (
    <div className="p-4 border-r border-gray-800 space-y-6 overflow-y-auto">
      {/* Strategy Selector */}
      <div className="space-y-2">
        <label className="block text-xs font-semibold text-gray-300 uppercase tracking-wider">
          Strategy
        </label>
        <select
          value={strategyType}
          onChange={(e) => setStrategyType(e.target.value as StrategyType)}
          disabled={isRunning}
          className="w-full px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm text-white disabled:opacity-50"
        >
          <option value="ema_crossover">EMA Crossover</option>
          <option value="rsi_threshold">RSI Threshold</option>
          <option value="macd_cross">MACD Cross</option>
          <option value="supertrend">Supertrend</option>
          <option value="momentum_breakout">Momentum Breakout</option>
          <option value="trend_following">Trend Following</option>
          <option value="mean_reversion">Mean Reversion</option>
          <option value="harmonic_setup">Harmonic Setup</option>
          <option value="yolo_pattern">YOLO Pattern</option>
          <option value="custom">Custom</option>
        </select>
      </div>

      {/* Symbol */}
      <div className="space-y-2">
        <label className="block text-xs font-semibold text-gray-300 uppercase tracking-wider">
          Symbol
        </label>
        <input
          type="text"
          placeholder="e.g. AAPL"
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          disabled={isRunning}
          className="w-full px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm text-white placeholder-gray-500 disabled:opacity-50"
        />
      </div>

      {/* Timeframe */}
      <div className="space-y-2">
        <label className="block text-xs font-semibold text-gray-300 uppercase tracking-wider">
          Timeframe
        </label>
        <select
          value={timeframe}
          onChange={(e) => setTimeframe(e.target.value as 'Daily' | 'Weekly')}
          disabled={isRunning}
          className="w-full px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm text-white disabled:opacity-50"
        >
          <option value="Daily">Daily</option>
          <option value="Weekly">Weekly</option>
        </select>
      </div>

      {/* Date Range */}
      <div className="space-y-2">
        <label className="block text-xs font-semibold text-gray-300 uppercase tracking-wider">
          Start Date
        </label>
        <input
          type="date"
          value={startDate}
          onChange={(e) => setStartDate(e.target.value)}
          disabled={isRunning}
          className="w-full px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm text-white disabled:opacity-50"
        />
      </div>

      <div className="space-y-2">
        <label className="block text-xs font-semibold text-gray-300 uppercase tracking-wider">
          End Date
        </label>
        <input
          type="date"
          value={endDate}
          onChange={(e) => setEndDate(e.target.value)}
          disabled={isRunning}
          className="w-full px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm text-white disabled:opacity-50"
        />
      </div>

      {/* Initial Capital */}
      <div className="space-y-2">
        <label className="block text-xs font-semibold text-gray-300 uppercase tracking-wider">
          Initial Capital ($)
        </label>
        <input
          type="number"
          min="100"
          step="100"
          value={initialCapital}
          onChange={(e) => setInitialCapital(Number(e.target.value))}
          disabled={isRunning}
          className="w-full px-3 py-2 rounded bg-gray-900 border border-gray-700 text-sm text-white disabled:opacity-50"
        />
      </div>

      {/* Dynamic Parameters */}
      {strategyParams.length > 0 && (
        <div className="space-y-3 border-t border-gray-800 pt-4">
          <div className="text-xs font-semibold text-gray-300 uppercase tracking-wider">
            Parameters
          </div>
          {strategyParams.map((param) => (
            <div key={param.name} className="space-y-1">
              <label className="text-xs text-gray-400">
                {param.name}
              </label>
              <input
                type="number"
                min={param.min}
                max={param.max}
                step={param.min < 1 ? 0.1 : 1}
                value={(parameters[param.name] as number) ?? param.default}
                onChange={(e) => setParameter(param.name, Number(e.target.value))}
                disabled={isRunning}
                className="w-full px-2 py-1.5 rounded bg-gray-900 border border-gray-700 text-xs text-white disabled:opacity-50"
              />
              <div className="text-xs text-gray-600">
                {param.min} to {param.max}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Error Banner */}
      {error && (
        <div className="rounded-lg border border-red-800 bg-red-950/40 px-3 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {/* Action Buttons */}
      <div className="flex flex-col gap-2 border-t border-gray-800 pt-4">
        <button
          onClick={() => { void handleRun() }}
          disabled={isRunning || !symbol || !startDate || !endDate}
          className="flex items-center justify-center gap-2 px-3 py-2 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-sm font-semibold text-white transition-colors"
        >
          {isRunning && <LoadingSpinner size="sm" />}
          {isRunning ? 'Running...' : 'Run Backtest'}
        </button>
        <button
          disabled={true}
          className="px-3 py-2 rounded bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-sm font-semibold text-white transition-colors"
          title="Coming soon: parameter sweep for optimization"
        >
          Run Sweep
        </button>
      </div>
    </div>
  )
}
