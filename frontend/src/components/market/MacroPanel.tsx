import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { createChart } from 'lightweight-charts';
import { marketApi } from '../../api/market';
import { LoadingSpinner } from '../shared/LoadingSpinner';

export function MacroPanel() {
  const chartRef = useRef<HTMLDivElement>(null);
  const { data: macroData, isLoading } = useQuery({
    queryKey: ['market', 'macro'],
    queryFn: marketApi.getMacro,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (!chartRef.current || !macroData || isLoading) return;

    const chart = createChart(chartRef.current, {
      layout: {
        background: { color: '#0a0a0f' },
        textColor: '#9ca3af',
      },
      width: chartRef.current.clientWidth,
      height: 300,
    });

    // Get DGS10 and DGS2 for yield spread calculation
    const dgs10Series = macroData.series.find((s) => s.name.includes('DGS10'));
    const dgs2Series = macroData.series.find((s) => s.name.includes('DGS2'));

    if (dgs10Series && dgs2Series) {
      const spreadSeries = chart.addLineSeries({
        color: '#8b5cf6',
        lineWidth: 2,
      });
      const chartData = macroData.labels.map((label, idx) => {
        const dgs10 = dgs10Series.data[idx] ?? 0;
        const dgs2 = dgs2Series.data[idx] ?? 0;
        return {
          time: label,
          value: dgs10 - dgs2,
        };
      });
      spreadSeries.setData(chartData);
      chart.timeScale().fitContent();
    }

    const handleResize = () => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth });
      }
    };
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.remove();
    };
  }, [macroData, isLoading]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <LoadingSpinner size="sm" />
      </div>
    );
  }

  if (!macroData || macroData.series.length === 0) {
    return (
      <div className="rounded-lg border border-gray-800 bg-gray-900 p-6">
        <h3 className="text-lg font-semibold text-white mb-4">Macro</h3>
        <div className="text-center py-8 text-gray-400 text-sm">
          FRED API key not configured or no data available
        </div>
      </div>
    );
  }

  const dgs10Series = macroData.series.find((s) => s.name.includes('DGS10'));
  const dgs2Series = macroData.series.find((s) => s.name.includes('DGS2'));
  const dxySeriesData = macroData.series.find((s) => s.name.includes('DXY'));

  const dgs10Latest = dgs10Series?.data[dgs10Series.data.length - 1];
  const dgs2Latest = dgs2Series?.data[dgs2Series.data.length - 1];
  const dxyLatest = dxySeriesData?.data[dxySeriesData.data.length - 1];

  const yieldSpread =
    dgs10Latest !== null &&
    dgs10Latest !== undefined &&
    dgs2Latest !== null &&
    dgs2Latest !== undefined
      ? dgs10Latest - dgs2Latest
      : null;

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-6">
      <h3 className="text-lg font-semibold text-white mb-4">Macro</h3>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-4">
        {yieldSpread !== null && (
          <div>
            <p className="text-xs text-gray-500 mb-1">Yield Spread (10y-2y)</p>
            <p className="text-2xl font-bold text-purple-400">{yieldSpread.toFixed(2)}%</p>
          </div>
        )}
        {dxyLatest !== null && dxyLatest !== undefined && (
          <div>
            <p className="text-xs text-gray-500 mb-1">DXY</p>
            <p className="text-2xl font-bold text-green-400">{dxyLatest.toFixed(2)}</p>
          </div>
        )}
        <div>
          <p className="text-xs text-gray-500 mb-1">Status</p>
          <p className="text-sm text-gray-300 mt-2">
            {dgs10Latest && dgs2Latest ? 'Data available' : 'Limited data'}
          </p>
        </div>
      </div>

      <div ref={chartRef} className="w-full" />
    </div>
  );
}
