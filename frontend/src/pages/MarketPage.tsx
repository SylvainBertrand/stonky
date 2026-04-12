import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { marketApi } from '../api/market';
import { MarketRegimeBanner } from '../components/market/MarketRegimeBanner';
import { BreadthPanel } from '../components/market/BreadthPanel';
import { MomentumPanel } from '../components/market/MomentumPanel';
import { MacroPanel } from '../components/market/MacroPanel';
import { SentimentPanel } from '../components/market/SentimentPanel';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';

type Tab = 'breadth' | 'momentum' | 'macro' | 'sentiment';

export function MarketPage() {
  const [activeTab, setActiveTab] = useState<Tab>('breadth');
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  const { data: regime, isLoading: regimeLoading } = useQuery({
    queryKey: ['market', 'regime'],
    queryFn: marketApi.getRegime,
    staleTime: 5 * 60 * 1000,
  });

  const handleRefresh = async () => {
    setIsRefreshing(true);
    setRefreshError(null);
    try {
      await marketApi.triggerRefresh();
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : 'Refresh failed');
    } finally {
      setIsRefreshing(false);
    }
  };

  if (regimeLoading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3">
        <div className="max-w-screen-xl mx-auto flex items-center justify-between gap-4">
          <div className="flex items-center gap-4">
            <h1 className="text-lg font-bold text-white tracking-tight">Stonky</h1>
            <nav className="flex items-center gap-3 text-sm">
              <Link to="/" className="text-gray-400 hover:text-white transition-colors">
                Scanner
              </Link>
              <span className="text-gray-700">|</span>
              <Link to="/watchlists" className="text-gray-400 hover:text-white transition-colors">
                Watchlists
              </Link>
              <span className="text-gray-700">|</span>
              <Link to="/backtest" className="text-gray-400 hover:text-white transition-colors">
                Backtest
              </Link>
              <span className="text-gray-700">|</span>
              <span className="text-white font-medium">Market</span>
            </nav>
          </div>
          <button
            onClick={() => {
              void handleRefresh();
            }}
            disabled={isRefreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded border border-gray-700 hover:border-gray-500 disabled:opacity-50 text-xs text-gray-400 hover:text-white transition-colors"
            title="Refresh market data"
          >
            {isRefreshing && <LoadingSpinner size="sm" />}
            {isRefreshing ? 'Refreshing…' : 'Refresh Data'}
          </button>
        </div>
      </header>

      <main className="max-w-screen-xl mx-auto px-6 py-4 space-y-6">
        {/* Error banner */}
        {refreshError && (
          <div className="rounded-lg border border-red-800 bg-red-950/40 px-4 py-2 text-sm text-red-400">
            {refreshError}
          </div>
        )}

        {/* Regime Banner */}
        {regime && <MarketRegimeBanner regime={regime} />}

        {/* Tab bar */}
        <div className="flex gap-2 border-b border-gray-800">
          <button
            onClick={() => setActiveTab('breadth')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'breadth'
                ? 'border-blue-400 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-300'
            }`}
          >
            Breadth
          </button>
          <button
            onClick={() => setActiveTab('momentum')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'momentum'
                ? 'border-blue-400 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-300'
            }`}
          >
            Momentum
          </button>
          <button
            onClick={() => setActiveTab('macro')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'macro'
                ? 'border-blue-400 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-300'
            }`}
          >
            Macro
          </button>
          <button
            onClick={() => setActiveTab('sentiment')}
            className={`px-4 py-3 text-sm font-medium border-b-2 transition-colors ${
              activeTab === 'sentiment'
                ? 'border-blue-400 text-blue-400'
                : 'border-transparent text-gray-400 hover:text-gray-300'
            }`}
          >
            Sentiment
          </button>
        </div>

        {/* Active panel */}
        <div>
          {activeTab === 'breadth' && <BreadthPanel />}
          {activeTab === 'momentum' && <MomentumPanel />}
          {activeTab === 'macro' && <MacroPanel />}
          {activeTab === 'sentiment' && <SentimentPanel />}
        </div>
      </main>
    </div>
  );
}
