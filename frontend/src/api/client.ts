export const API_BASE = (import.meta.env.VITE_API_URL as string | undefined) ?? ''

const FETCH_TIMEOUT_MS = 30_000

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const signal = AbortSignal.timeout(FETCH_TIMEOUT_MS)
  const res = await fetch(`${API_BASE}${path}`, { ...init, signal })
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}${body ? `: ${body}` : ''}`)
  }
  return res.json() as Promise<T>
}
