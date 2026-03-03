import type { SAImportResult, Watchlist, WatchlistItemWithRatings } from '../types'

const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, init)
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${body ? `: ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}

// For 404 that should return null (e.g. GET /active when no active watchlist)
async function apiFetchNullable<T>(path: string): Promise<T | null> {
  const res = await fetch(`${API_BASE}${path}`)
  if (res.status === 404) return null
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${body ? `: ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}

export const watchlistApi = {
  getAll: (): Promise<Watchlist[]> =>
    apiFetch<Watchlist[]>('/api/watchlists'),

  getActive: (): Promise<Watchlist | null> =>
    apiFetchNullable<Watchlist>('/api/watchlists/active'),

  create: (name: string): Promise<Watchlist> =>
    apiFetch<Watchlist>('/api/watchlists', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  update: (id: number, name: string): Promise<Watchlist> =>
    apiFetch<Watchlist>(`/api/watchlists/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name }),
    }),

  delete: (id: number): Promise<void> =>
    apiFetch<void>(`/api/watchlists/${id}`, { method: 'DELETE' }),

  setActive: (id: number): Promise<Watchlist> =>
    apiFetch<Watchlist>('/api/watchlists/active', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ watchlist_id: id }),
    }),

  getItems: (id: number): Promise<WatchlistItemWithRatings[]> =>
    apiFetch<WatchlistItemWithRatings[]>(`/api/watchlists/${id}/items`),

  addSymbol: (id: number, ticker: string): Promise<unknown> =>
    apiFetch(`/api/watchlists/${id}/items`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker }),
    }),

  removeSymbol: (id: number, ticker: string): Promise<void> =>
    apiFetch<void>(`/api/watchlists/${id}/items/${encodeURIComponent(ticker)}`, {
      method: 'DELETE',
    }),

  importSA: (id: number, file: File): Promise<SAImportResult> => {
    const form = new FormData()
    form.append('file', file)
    return apiFetch<SAImportResult>(`/api/watchlists/${id}/import-sa`, {
      method: 'POST',
      body: form,
    })
  },
}
