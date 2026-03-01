import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query'

const queryClient = new QueryClient()

interface HealthResponse {
  status: string
  db: string
  detail?: string
}

async function fetchHealth(): Promise<HealthResponse> {
  const res = await fetch('/api/health')
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json() as Promise<HealthResponse>
}

function StatusBadge({ value, ok }: { value: string; ok: boolean }) {
  return (
    <span
      className={`inline-block rounded px-2 py-0.5 text-sm font-mono font-semibold ${
        ok ? 'bg-green-900 text-green-300' : 'bg-red-900 text-red-300'
      }`}
    >
      {value}
    </span>
  )
}

function HealthPanel() {
  const { data, isLoading, isError, error } = useQuery<HealthResponse, Error>({
    queryKey: ['health'],
    queryFn: fetchHealth,
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return <p className="text-gray-400 text-sm animate-pulse">Checking backend…</p>
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-red-800 bg-red-950 p-4 text-sm">
        <p className="font-semibold text-red-400">Backend unreachable</p>
        <p className="mt-1 text-red-500 font-mono text-xs">{error.message}</p>
      </div>
    )
  }

  const isOk = data?.status === 'ok'
  const dbOk = data?.db === 'connected'

  return (
    <div className="rounded-lg border border-gray-700 bg-gray-900 p-4 space-y-3 text-sm w-72">
      <div className="flex items-center justify-between">
        <span className="text-gray-400">API</span>
        <StatusBadge value={data?.status ?? '—'} ok={isOk} />
      </div>
      <div className="flex items-center justify-between">
        <span className="text-gray-400">Database</span>
        <StatusBadge value={data?.db ?? '—'} ok={dbOk} />
      </div>
      {data?.detail && (
        <p className="text-xs text-red-400 font-mono break-all">{data.detail}</p>
      )}
    </div>
  )
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <div className="min-h-screen p-8">
        <header className="mb-8">
          <h1 className="text-2xl font-bold tracking-tight text-white">Stonky</h1>
          <p className="mt-1 text-sm text-gray-500">Investment analysis platform</p>
        </header>

        <section>
          <h2 className="mb-3 text-xs font-semibold uppercase tracking-widest text-gray-500">
            System Status
          </h2>
          <HealthPanel />
        </section>
      </div>
    </QueryClientProvider>
  )
}
