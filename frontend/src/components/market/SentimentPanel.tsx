import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { createChart } from 'lightweight-charts'
import { marketApi } from '../../api/market'
import { LoadingSpinner } from '../shared/LoadingSpinner'

export function SentimentPanel() {
  const chartRef = useRef<HTMLDivElement>(null)
  const { data: sentimentData, isLoading } = useQuery({
    queryKey: ['market', 'sentiment'],
    queryFn: marketApi.getSentiment,
    staleTime: 5 * 60 * 1000,
  })

  useEffect(() => {
    if (!chartRef.current || !sentimentData || isLoading) return

    const chart = createChart(chartRef.current, {
      layout: {
        background: { color: '#0a0a0f' },
        textColor: '#9ca3af',
      },
      width: chartRef.current.clientWidth,
      height: 300,
    })

    const aaiiBullSeries = sentimentData.series.find((s) => s.name.includes('AAII') && s.name.includes('Bull'))
    const aaiiBearSeries = sentimentData.series.find((s) => s.name.includes('AAII') && s.name.includes('Bear'))

    if (aaiiBullSeries) {
      const bullSeries = chart.addLineSeries({
        color: '#4ade80',
        lineWidth: 2,
      })
      const chartData = sentimentData.labels.map((label, idx) => ({
        time: label,
        value: aaiiBullSeries.data[idx] ?? 0,
      }))
      bullSeries.setData(chartData)
    }

    if (aaiiBearSeries) {
      const bearSeries = chart.addLineSeries({
        color: '#ef4444',
        lineWidth: 2,
      })
      const chartData = sentimentData.labels.map((label, idx) => ({
        time: label,
        value: aaiiBearSeries.data[idx] ?? 0,
      }))
      bearSeries.setData(chartData)
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
  }, [sentimentData, isLoading])

  if (isLoading) {
    return (
      <div className="flex justify-center py-8">
        <LoadingSpinner size="sm" />
      </div>
    )
  }

  if (!sentimentData || sentimentData.series.length === 0) {
    return (
      <div className="text-center py-8 text-gray-400">
        No sentiment data available
      </div>
    )
  }

  const aaiiBullSeries = sentimentData.series.find((s) => s.name.includes('AAII') && s.name.includes('Bull'))
  const aaiiBearSeries = sentimentData.series.find((s) => s.name.includes('AAII') && s.name.includes('Bear'))

  const bullLatest = aaiiBullSeries?.data[aaiiBullSeries.data.length - 1]
  const bearLatest = aaiiBearSeries?.data[aaiiBearSeries.data.length - 1]

  return (
    <div className="rounded-lg border border-gray-800 bg-gray-900 p-6">
      <h3 className="text-lg font-semibold text-white mb-4">Sentiment</h3>

      {/* Stats */}
      <div className="flex gap-4 mb-4">
        {bullLatest !== null && bullLatest !== undefined && (
          <div>
            <p className="text-xs text-gray-500 mb-1">AAII Bull</p>
            <p className="text-2xl font-bold text-green-400">{bullLatest.toFixed(1)}%</p>
          </div>
        )}
        {bearLatest !== null && bearLatest !== undefined && (
          <div>
            <p className="text-xs text-gray-500 mb-1">AAII Bear</p>
            <p className="text-2xl font-bold text-red-400">{bearLatest.toFixed(1)}%</p>
          </div>
        )}
      </div>

      <div ref={chartRef} className="w-full" />
    </div>
  )
}
