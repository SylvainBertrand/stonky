import { useState, useRef, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { scannerApi, synthesisApi } from '../api/scanner';
import { useStockStore } from '../stores/stockStore';
import type { OHLCVBar } from '../types';
import { CandlestickChart } from '../components/stock/CandlestickChart';
import type { ChartHandle } from '../components/stock/CandlestickChart';
import { ChartControls, DEFAULT_OVERLAYS } from '../components/stock/ChartControls';
import type { OverlayKey, OverlayToggles } from '../components/stock/ChartControls';
import { CategoryScoresPanel } from '../components/stock/CategoryScores';
import { SignalsPanel } from '../components/stock/SignalsPanel';
import { HarmonicBanner } from '../components/stock/HarmonicBanner';
import { ChartPatternsBanner } from '../components/stock/ChartPatternsBanner';
import { ElliottWaveBanner } from '../components/stock/ElliottWaveBanner';
import { useEWPatterns } from '../hooks/useEWPatterns';
import { ForecastBanner } from '../components/stock/ForecastBanner';
import { useForecast } from '../hooks/useForecast';
import { TradeSetupCard } from '../components/stock/TradeSetupCard';
import { ProfileBadge } from '../components/scanner/ProfileBadge';
import { LoadingSpinner } from '../components/shared/LoadingSpinner';
import { ScoreDisplay } from '../components/shared/ScoreDisplay';
import type { CategoryScores } from '../types';

export function StockDetailPage() {
  const { symbol = '' } = useParams<{ symbol: string }>();
  const navigate = useNavigate();
  const { chartTimeframe, setChartTimeframe } = useStockStore();
  const [selectedCategory, setSelectedCategory] = useState<keyof CategoryScores | null>(null);
  const [overlays, setOverlays] = useState<OverlayToggles>(DEFAULT_OVERLAYS);
  const chartRef = useRef<ChartHandle>(null);

  // Dynamic bar loading
  const [allBars, setAllBars] = useState<OHLCVBar[]>([]);
  const [hasMore, setHasMore] = useState(true);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const handleToggle = (key: OverlayKey) => {
    setOverlays((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const {
    data: detail,
    isLoading: detailLoading,
    isError: detailError,
  } = useQuery({
    queryKey: ['scanner', 'detail', symbol, chartTimeframe],
    queryFn: () => scannerApi.getDetail(symbol, chartTimeframe),
    enabled: !!symbol,
    staleTime: 60_000,
  });

  const { data: ohlcv, isLoading: chartLoading } = useQuery({
    queryKey: ['stocks', symbol, 'ohlcv', chartTimeframe],
    queryFn: () => scannerApi.getOHLCV(symbol, chartTimeframe),
    enabled: !!symbol,
    staleTime: 120_000,
  });

  const { data: ewData } = useEWPatterns(symbol, chartTimeframe);
  const { data: forecastData } = useForecast(symbol, chartTimeframe);

  const { data: synthesisData, isLoading: synthesisLoading } = useQuery({
    queryKey: ['synthesis', symbol],
    queryFn: () => synthesisApi.getSynthesis(symbol),
    enabled: !!symbol,
    staleTime: 300_000,
  });

  // Initialize allBars when ohlcv changes
  useEffect(() => {
    if (ohlcv) {
      setAllBars(ohlcv.bars);
      setHasMore(ohlcv.has_more);
    }
  }, [ohlcv]);

  const handleLoadMore = useCallback(async () => {
    if (isLoadingMore || !hasMore || allBars.length === 0) return;
    setIsLoadingMore(true);
    try {
      const oldestBar = allBars[0];
      const beforeDate =
        typeof oldestBar.time === 'number'
          ? new Date(oldestBar.time * 1000).toISOString()
          : oldestBar.time;
      const more = await scannerApi.loadMoreBars(symbol, chartTimeframe, beforeDate);
      if (more && more.bars.length > 0) {
        setAllBars((prev) => [...more.bars, ...prev]);
        setHasMore(more.has_more);
      } else {
        setHasMore(false);
      }
    } catch {
      // silently fail — user can retry by scrolling again
    } finally {
      setIsLoadingMore(false);
    }
  }, [isLoadingMore, hasMore, allBars, symbol, chartTimeframe]);

  if (detailLoading) {
    return (
      <div className="flex justify-center items-center min-h-screen">
        <LoadingSpinner size="lg" />
      </div>
    );
  }

  if (detailError || !detail) {
    return (
      <div className="min-h-screen flex flex-col items-center justify-center gap-4">
        <p className="text-red-400">No analysis data for {symbol}.</p>
        <button onClick={() => navigate('/')} className="text-sm text-blue-400 hover:underline">
          ← Back to scanner
        </button>
      </div>
    );
  }

  if (!detail.meta) return null;
  const chgPct = detail.meta.price_change_pct;
  const chgColor = chgPct > 0 ? 'text-green-400' : chgPct < 0 ? 'text-red-400' : 'text-gray-400';

  return (
    <div className="min-h-screen">
      {/* Header */}
      <header className="border-b border-gray-800 px-6 py-3">
        <div className="max-w-screen-xl mx-auto flex items-center gap-4 flex-wrap">
          <button
            onClick={() => navigate('/')}
            className="text-sm text-gray-400 hover:text-gray-200 transition-colors shrink-0"
          >
            ← Back
          </button>
          <span className="font-bold text-xl text-white font-mono">{detail.symbol}</span>
          <span className="font-mono text-lg text-gray-200">
            ${detail.meta.last_price.toFixed(2)}
          </span>
          <span className={`font-mono text-sm ${chgColor}`}>
            {chgPct >= 0 ? '+' : ''}
            {chgPct.toFixed(2)}%
          </span>
          <div className="flex items-center gap-1 ml-auto">
            <span className="text-xs text-gray-500 mr-2">Score</span>
            <ScoreDisplay score={detail.composite_score} showBar />
          </div>
          {detail.profile_matches.map((p) => (
            <ProfileBadge key={p} profile={p} />
          ))}
        </div>
      </header>

      <main className="max-w-screen-xl mx-auto px-6 py-4 space-y-4">
        {/* Trade setup card */}
        <TradeSetupCard synthesis={synthesisData} isLoading={synthesisLoading} />

        {/* Timeframe selector + Chart */}
        <div>
          <div className="flex gap-1 mb-2">
            {[
              { key: '1h' as const, label: '1H' },
              { key: '4h' as const, label: '4H' },
              { key: '1d' as const, label: '1D' },
              { key: '1w' as const, label: '1W' },
              { key: '1mo' as const, label: '1M' },
            ].map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setChartTimeframe(key)}
                className={`px-3 py-1 rounded text-xs font-medium transition-colors ${
                  chartTimeframe === key
                    ? 'bg-blue-600 text-white'
                    : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
          <ChartControls
            overlays={overlays}
            onToggle={handleToggle}
            onReset={() => chartRef.current?.fitContent()}
          />
          {chartLoading ? (
            <div className="flex justify-center items-center h-[420px] bg-gray-900 rounded">
              <LoadingSpinner size="lg" />
            </div>
          ) : ohlcv && ohlcv.bars.length > 0 ? (
            <CandlestickChart
              ref={chartRef}
              data={ohlcv}
              allBars={allBars}
              height={420}
              detections={detail.chart_patterns ?? []}
              overlays={overlays}
              ewWaves={ewData?.waves ?? null}
              ewDirection={ewData?.direction ?? null}
              forecastData={overlays.forecast ? (forecastData ?? null) : null}
              onLoadMore={handleLoadMore}
              isLoadingMore={isLoadingMore}
              hasMore={hasMore}
            />
          ) : ohlcv &&
            ohlcv.bars.length === 0 &&
            (chartTimeframe === '1h' || chartTimeframe === '4h') ? (
            <div className="flex justify-center items-center h-[420px] bg-gray-900/50 rounded border border-gray-700/40 text-gray-500 text-sm">
              Intraday data not yet available — runs nightly
            </div>
          ) : (
            <div className="flex justify-center items-center h-[420px] bg-gray-900/50 rounded border border-gray-700/40 text-gray-500 text-sm">
              No OHLCV data available. Trigger a data refresh first.
            </div>
          )}
        </div>

        {/* Category + Signals panels */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 p-4">
            <CategoryScoresPanel
              scores={detail.category_scores}
              selected={selectedCategory}
              onSelect={setSelectedCategory}
            />
          </div>
          <div className="rounded-lg border border-gray-700/50 bg-gray-900/40 p-4 overflow-y-auto max-h-80">
            <SignalsPanel signals={detail.signals} highlightCategory={selectedCategory} />
          </div>
        </div>

        {/* Harmonic banner */}
        {detail.harmonics?.detected && <HarmonicBanner harmonic={detail.harmonics} />}

        {/* Chart patterns banner (YOLOv8) */}
        <ChartPatternsBanner patterns={detail.chart_patterns ?? []} scannedAt={detail.scanned_at} />

        {/* Elliott Wave banner */}
        <ElliottWaveBanner detection={ewData} />

        {/* Chronos-2 forecast banner */}
        <ForecastBanner forecast={forecastData} />

        {/* Volume contradiction warning */}
        {detail.volume_contradiction && (
          <div className="rounded-lg border border-yellow-700/40 bg-yellow-950/30 px-4 py-2 text-xs text-yellow-400">
            ⚠ Volume contradiction: OBV and CMF oppose the composite signal direction.
          </div>
        )}

        {/* Meta footer */}
        <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-gray-500 pb-4">
          <span>
            ATR: <span className="text-gray-300">{detail.meta.atr.toFixed(4)}</span>
          </span>
          <span>
            ATR%: <span className="text-gray-300">{detail.meta.atr_pct.toFixed(2)}%</span>
          </span>
          <span>
            Vol ratio: <span className="text-gray-300">{detail.meta.volume_ratio.toFixed(2)}×</span>
          </span>
          <span>
            Bars: <span className="text-gray-300">{detail.meta.bars}</span>
          </span>
          <span>
            Last bar: <span className="text-gray-300">{detail.meta.timestamp.slice(0, 10)}</span>
          </span>
        </div>
      </main>
    </div>
  );
}
