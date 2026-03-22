import { create } from 'zustand'

export type ChartTimeframe = '1h' | '4h' | '1d' | '1w' | '1mo'

interface StockStore {
  /** Timeframe selected in the chart — persists across navigation */
  chartTimeframe: ChartTimeframe
  setChartTimeframe: (tf: ChartTimeframe) => void
}

export const useStockStore = create<StockStore>((set) => ({
  chartTimeframe: '1d',
  setChartTimeframe: (tf) => set({ chartTimeframe: tf }),
}))
