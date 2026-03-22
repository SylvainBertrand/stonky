import { useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useBacktestStore } from '../stores/backtestStore'
import { StrategyConfigurator } from '../components/backtest/StrategyConfigurator'
import { BacktestSummaryStats } from '../components/backtest/BacktestSummaryStats'
import { EquityCurveChart } from '../components/backtest/EquityCurveChart'
import { TradeListTable } from '../components/backtest/TradeListTable'
import { ParameterSweepHeatmap } from '../components/backtest/ParameterSweepHeatmap'

export function BacktestPage() {
  const {
    result,
    sweepResult,
    selectedSweepIndex,
    setSelectedSweepIndex,
  } = useBacktestStore()

  // Select best result by default when sweep completes
  useEffect(() => {
    if (sweepResult && selectedSweepIndex === null) {
      setSelectedSweepIndex(sweepResult.best_index)
    }
  }, [sweepResult, selectedSweepIndex, setSelectedSweepIndex])

  const displayResult = selectedSweepIndex !== null && sweepResult
    ? sweepResult.results[selectedSweepIndex]
    : result

  return (
    <div className="min-h-screen flex flex-col">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3">
        <div className="max-w-screen-2xl mx-auto flex items-center justify-between gap-4">
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
              <Link
                to="/watchlists"
                className="text-gray-400 hover:text-white transition-colors"
              >
                Watchlists
              </Link>
              <span className="text-gray-700">|</span>
              <span className="text-white font-medium">Backtest</span>
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

      {/* Main content */}
      <main className="flex flex-1 overflow-hidden">
        {/* Left panel: Strategy configurator (30%) */}
        <div className="w-[30%] border-r border-gray-800 overflow-y-auto bg-gray-900/30">
          <StrategyConfigurator />
        </div>

        {/* Right panel: Results (70%) */}
        <div className="flex-1 overflow-y-auto">
          <div className="p-6 space-y-6 max-w-screen-xl">
            {displayResult ? (
              <>
                {/* Summary Stats */}
                <div>
                  <h2 className="text-lg font-semibold text-white mb-4">Performance Summary</h2>
                  <BacktestSummaryStats
                    stats={displayResult.stats}
                    benchmarkReturn={displayResult.benchmark_return_pct}
                    benchmarkSharpe={displayResult.benchmark_sharpe}
                  />
                </div>

                {/* Equity Curve */}
                <div>
                  <h2 className="text-lg font-semibold text-white mb-4">Equity Curve & Drawdown</h2>
                  <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-4 overflow-hidden">
                    <EquityCurveChart
                      equity={displayResult.equity_curve}
                      drawdown={displayResult.drawdown_curve}
                      height={300}
                    />
                  </div>
                </div>

                {/* Parameter Sweep Heatmap */}
                {sweepResult && (
                  <div>
                    <h2 className="text-lg font-semibold text-white mb-4">Parameter Optimization</h2>
                    <ParameterSweepHeatmap
                      sweepResult={sweepResult}
                      onSelectCell={setSelectedSweepIndex}
                    />
                  </div>
                )}

                {/* Trade List */}
                <div>
                  <h2 className="text-lg font-semibold text-white mb-4">
                    Trade History ({displayResult.stats.total_trades} trades)
                  </h2>
                  <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-4">
                    <TradeListTable trades={displayResult.trades} />
                  </div>
                </div>
              </>
            ) : (
              <div className="rounded-lg border border-gray-800 bg-gray-900/50 p-8 text-center">
                <div className="text-gray-500">
                  <p className="text-lg font-semibold mb-2">No backtest results yet</p>
                  <p className="text-sm">Configure a strategy and click "Run Backtest" to see results here</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
