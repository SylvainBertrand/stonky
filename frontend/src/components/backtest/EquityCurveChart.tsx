import { useEffect, useRef } from 'react';
import {
  createChart,
  type IChartApi,
  type LineData,
  type HistogramData,
  type Time,
} from 'lightweight-charts';
import type { EquityCurvePoint, DrawdownPoint } from '../../types';

interface Props {
  equity: EquityCurvePoint[];
  drawdown: DrawdownPoint[];
  height?: number;
}

export function EquityCurveChart({ equity, drawdown, height = 400 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || equity.length === 0) return;

    // Clean up previous chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    // Create chart
    const chart = createChart(container, {
      layout: {
        background: { color: '#0d1117' },
        textColor: '#8b949e',
      },
      grid: {
        vertLines: { color: '#21262d' },
        horzLines: { color: '#21262d' },
      },
      crosshair: {
        vertLine: { color: '#444d56' },
        horzLine: { color: '#444d56' },
      },
      rightPriceScale: { borderColor: '#30363d' },
      timeScale: {
        borderColor: '#30363d',
        timeVisible: false,
      },
      width: container.clientWidth,
      height,
    });
    chartRef.current = chart;

    // Equity curve (left price scale)
    const equitySeries = chart.addLineSeries({
      color: '#22c55e',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
      crosshairMarkerVisible: true,
    });

    const equityData: LineData[] = equity.map((p) => ({
      time: p.date as unknown as Time,
      value: p.value,
    }));
    equitySeries.setData(equityData);

    // Drawdown histogram (bottom 20%)
    const drawdownSeries = chart.addHistogramSeries({
      priceScaleId: 'drawdown',
      color: '#ef4444',
      priceFormat: { type: 'volume' },
    });
    chart.priceScale('drawdown').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    const drawdownData: HistogramData[] = drawdown.map((p) => ({
      time: p.date as unknown as Time,
      value: Math.abs(p.pct), // Show as positive magnitude
      color: '#ef444466',
    }));
    drawdownSeries.setData(drawdownData);

    chart.timeScale().fitContent();

    // Resize observer
    const observer = new ResizeObserver(() => {
      if (container && chartRef.current) {
        chartRef.current.applyOptions({ width: container.clientWidth });
      }
    });
    observer.observe(container);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  }, [equity, drawdown, height]);

  return (
    <div
      ref={containerRef}
      style={{ position: 'relative', height }}
      className="rounded overflow-hidden"
    />
  );
}
