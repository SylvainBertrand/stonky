import { useEffect, useRef } from 'react';
import { useQuery } from '@tanstack/react-query';
import { createChart } from 'lightweight-charts';
import { marketApi } from '../../api/market';
import { LoadingSpinner } from '../shared/LoadingSpinner';

export function BreadthPanel() {
  const chartRef = useRef<HTMLDivElement>(null);
  const { data: breadthData, isLoading } = useQuery({
    queryKey: ['market', 'breadth'],
    queryFn: marketApi.getBreadth,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (!chartRef.current || !breadthData || isLoading) return;

    const chart = createChart(chartRef.current, {
      layout: {
        background: { color: '#0a0a0f' },
        textColor: '#9ca3af',
      },
      width: chartRef.current.clientWidth,
      height: 300,
    });

    const timeSeries = chart.addLineSeries({
      color: '#4ade80',
      lineWidth: 2,
    });

    const ratioSeries = breadthData.series.find((s) => s.name.includes('ratio'));
    if (ratioSeries && ratioSeries.data.length > 0) {
      const chartData = breadthData.labels.map((label, idx) => ({
        time: label,
        value: ratioSeries.data[idx] ?? 0,
      }));
      timeSeries.setData(chartData);
    }

    chart.timeScale().fitContent();

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
  }, [breadthData, isLoading]);

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <LoadingSpinner size="sm" />
      </div>
    );
  }

  if (!breadthData || breadthData.series.length === 0) {
    return <div className="text-center py-8 text-gray-400">No breadth data available</div>;
  }

  const ratioSeries = breadthData.series.find((s) => s.name.includes('ratio'));
  const latestValue = ratioSeries?.data[ratioSeries.data.length - 1];

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-6">
      <h3 className="text-lg font-semibold text-white mb-4">Breadth</h3>
      <div className="mb-4">
        {latestValue !== null && latestValue !== undefined && (
          <div className="flex items-baseline gap-2">
            <span className="text-3xl font-bold text-white">{latestValue.toFixed(3)}</span>
            <span className="text-sm text-gray-400">SPX/RSP Ratio</span>
          </div>
        )}
      </div>
      <div ref={chartRef} className="w-full" />
    </div>
  );
}
