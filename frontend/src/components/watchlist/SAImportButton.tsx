import { useRef, useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { watchlistApi } from '../../api/watchlists'
import type { SAImportResult } from '../../types'
import { LoadingSpinner } from '../shared/LoadingSpinner'

interface Props {
  watchlistId: number
}

export function SAImportButton({ watchlistId }: Props) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [result, setResult] = useState<SAImportResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const queryClient = useQueryClient()

  const mutation = useMutation({
    mutationFn: (file: File) => watchlistApi.importSA(watchlistId, file),
    onSuccess: (data) => {
      setResult(data)
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['watchlist', watchlistId, 'items'] })
      void queryClient.invalidateQueries({ queryKey: ['watchlists'] })
    },
    onError: (err: Error) => {
      setError(err.message)
      setResult(null)
    },
  })

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setResult(null)
    setError(null)
    mutation.mutate(file)
    // Reset input so same file can be re-imported
    e.target.value = ''
  }

  return (
    <div className="flex items-center gap-2">
      <input
        ref={fileInputRef}
        type="file"
        accept=".csv,.xlsx,.xls"
        className="hidden"
        onChange={handleFileChange}
      />
      <button
        onClick={() => fileInputRef.current?.click()}
        disabled={mutation.isPending}
        className="flex items-center gap-1.5 px-3 py-1.5 rounded bg-gray-700 hover:bg-gray-600 disabled:opacity-50 text-xs font-medium text-gray-200 transition-colors"
      >
        {mutation.isPending && <LoadingSpinner size="sm" />}
        {mutation.isPending ? 'Importing…' : 'Import SA Spreadsheet'}
      </button>
      {result && (
        <span className="text-xs text-green-400">
          +{result.added} added, {result.ratings_imported} ratings updated
          {result.skipped > 0 && `, ${result.skipped} skipped`}
          {result.errors > 0 && (
            <span className="text-yellow-400">, {result.errors} errors</span>
          )}
        </span>
      )}
      {error && <span className="text-xs text-red-400">{error}</span>}
    </div>
  )
}
