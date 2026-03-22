import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createChart } from 'lightweight-charts'
import { marketApi } from '../../api/market'
import { LoadingSpinner } from '../shared/LoadingSpinner'

export function MomentumPanel() {
  const chartRef = useRef<HTMLDivElement>(null)
  const [activeChart, setActiveChart] = useState<'spx' | 'vix'>('spx')
  const { data: momentumData, isLoading } = useQuery({
    queryKey: ['market', 'momentum'],
    queryFn: marketApi.getMomentum,
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (!chartRef.current || !momentumData || isLoading) return

    const chart = createChart(chartRef.current, {
      layout: {
        background: { color: '#0a0a0f' },
        textColor: '#9ca3af',
      },
      width: chartRef.current.clientWidth,
      height: 300,
    })

    const spxSeries = momentumData.series.find((s) => s.name.includes('SPX'))
    const vixSeries = momentumData.series.find((s) => s.name.includes('VIX'))

    if (activeChart === 'spx' && spxSeries) {
      const lineSeries = chart.addLineSeries({
        color: '#60a5fa',
        lineWidth: 2,
      })
      const chartData = momentumData.labels.map((label, idx) => ({
        time: label,
        value: spxSeries.data[idx] ?? 0,
      }))
      lineSeries.setData(chartData)
    } else if (activeChart === 'vix' && vixSeries) {
      const lineSeries = chart.addLineSeries({
        color: '#ef4444',
        lineWidth: 2,
      })
      const chartData = momentumData.labels.map((label, idx) => ({
        time: label,
        value: vixSeries.data[idx] ?? 0,
      }))
      lineSeries.setData(chartData)
    }

    chart.timeScale().fitContent()

    const handleResize = () => {
      if (chartRef.current) {
        chart.applyOptions({ width: chartRef.current.clientWidth })
      }
    }
    window.addEventListener('resize', handleResize)
    return () => {
      window.removeEventListener('resize', handleResize)
      chart.remove()
    }
  }, [momentumData, isLoading, activeChart])

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <LoadingSpinner size="sm" />
      </div>
    )
  }

  if (!momentumData || momentumData.series.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400">
        No momentum data available
      </div>
    )
  }

  const spxSeries = momentumData.series.find((s) => s.name.includes('SPX'))
  const vixSeries = momentumData.series.find((s) => s.name.includes('VIX'))

  const spxLatest = spxSeries?.data[spxSeries.data.length - 1]
  const vixLatest = vixSeries?.data[vixSeries.data.length - 1]

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-6">
      <h3 className="text-lg font-semibold text-white mb-4">Momentum</h3>

      {/* Chart tabs */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setActiveChart('spx')}
          className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
            activeChart === 'spx'
              ? 'bg-blue-600 text-white'
              : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
          }`}
        >
          SPX
        </button>
        <button
          onClick={() => setActiveChart('vix')}
          className={`px-3 py-1 rounded text-sm font-medium transition-colors ${
            activeChart === 'vix'
              ? 'bg-red-600 text-white'
              : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
          }`}
        >
          VIX
        </button>
      </div>

      {/* Stats */}
      <div className="flex gap-4 mb-4">
        {spxLatest !== null && spxLatest !== undefined && (
          <div>
            <p className="text-xs text-gray-500 mb-1">SPX Close</p>
            <p className="text-2xl font-bold text-blue-400">{spxLatest.toFixed(0)}</p>
          </div>
        )}
        {vixLatest !== null && vixLatest !== undefined && (
          <div>
            <p className="text-xs text-gray-500 mb-1">VIX</p>
            <p className="text-2xl font-bold text-red-400">{vixLatest.toFixed(2)}</p>
          </div>
        )}
      </div>

      <div ref={chartRef} className="w-full" />
    </div>
  )
}
