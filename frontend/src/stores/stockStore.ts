import { create } from 'zustand'

interface StockStore {
  /** Timeframe selected in the chart — persists across navigation */
  chartTimeframe: '1d' | '1w'
  setChartTimeframe: (tf: '1d' | '1w') => void
}

export const useStockStore = create<StockStore>((set) => ({
  chartTimeframe: '1d',
  setChartTimeframe: (tf) => set({ chartTimeframe: tf }),
}))
