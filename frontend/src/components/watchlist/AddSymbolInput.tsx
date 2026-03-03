import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { watchlistApi } from '../../api/watchlists'

interface Props {
  watchlistId: number
}

export function AddSymbolInput({ watchlistId }: Props) {
  const [ticker, setTicker] = useState('')
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const inputRef = useRef<HTMLInputElement>(null)

  const mutation = useMutation({
    mutationFn: (t: string) => watchlistApi.addSymbol(watchlistId, t),
    onSuccess: () => {
      setTicker('')
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['watchlist', watchlistId, 'items'] })
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] })
    },
    onError: (err: Error) => {
      if (err.message.includes('409')) {
        setError(`${ticker.toUpperCase()} is already in this watchlist`)
      } else {
        setError(err.message)
      }
    },
  })

  const handleSubmit = () => {
    const t = ticker.trim().toUpperCase()
    if (!t) return
    setError(null)
    mutation.mutate(t)
  }

  return (
    <div className="space-y-1">
      <div className="flex gap-2">
        <input
          ref={inputRef}
          type="text"
          value={ticker}
          onChange={(e) => setTicker(e.target.value.toUpperCase())}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSubmit()
            if (e.key === 'Escape') setTicker('')
          }}
          placeholder="Add ticker (e.g. AAPL)"
          className="flex-1 px-2 py-1.5 rounded bg-gray-800 border border-gray-700 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500"
        />
        <button
          onClick={handleSubmit}
          disabled={mutation.isPending || !ticker.trim()}
          className="px-3 py-1.5 rounded bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-xs font-semibold text-white transition-colors"
        >
          {mutation.isPending ? '…' : 'Add'}
        </button>
      </div>
      {error && <p className="text-xs text-red-400">{error}</p>}
    </div>
  )
}
