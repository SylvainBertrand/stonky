import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { ScannerPage } from './pages/ScannerPage'
import { StockDetailPage } from './pages/StockDetailPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<ScannerPage />} />
          <Route path="/stock/:symbol" element={<StockDetailPage />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}
