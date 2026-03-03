import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it } from 'vitest'
import { http, HttpResponse } from 'msw'
import { server } from '../test/mocks/server'
import {
  MOCK_RESULTS,
  MOCK_RUN_COMPLETED,
  MOCK_RUN_FAILED,
  MOCK_RUN_PENDING,
} from '../test/mocks/handlers'
import App, { queryClient } from '../App'
import { useScannerStore } from '../stores/scannerStore'

// Helper: render the full App (which includes ScannerPage at /)
function renderApp() {
  return render(<App />)
}

beforeEach(() => {
  // Reset Zustand store to initial state so tests don't bleed into each other
  useScannerStore.setState({
    activeProfile: null,
    isScanning: false,
    activeRunId: null,
    scanStartTime: null,
    lastFetched: null,
  })
  // Clear React Query cache so each test gets a fresh fetch
  queryClient.clear()
})

describe('ScannerPage', () => {
  it('renders the scanner page with Run Scan button', () => {
    renderApp()
    expect(screen.getByText('Stonky')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /run scan/i })).toBeInTheDocument()
  })

  it('shows "Not yet scanned" status when no results have been fetched', async () => {
    server.use(
      http.get('/api/scanner/results', () => HttpResponse.json([]))
    )
    renderApp()
    await waitFor(() => {
      expect(screen.getByText('Not yet scanned')).toBeInTheDocument()
    })
  })

  it('shows "No results yet" placeholder when results list is empty', async () => {
    server.use(
      http.get('/api/scanner/results', () => HttpResponse.json([]))
    )
    renderApp()
    await waitFor(() => {
      expect(screen.getByText(/no results yet/i)).toBeInTheDocument()
    })
  })

  it('shows results table when results are returned', async () => {
    renderApp()
    await waitFor(() => {
      expect(screen.getByText('AAPL')).toBeInTheDocument()
    })
    expect(screen.getByText('MSFT')).toBeInTheDocument()
  })

  it('shows "Scanning…" on button while scan is in progress', async () => {
    // Return pending status so scanning doesn't complete immediately
    server.use(
      http.get('/api/scanner/runs/:runId', () => HttpResponse.json(MOCK_RUN_PENDING))
    )
    const user = userEvent.setup()
    renderApp()
    const button = screen.getByRole('button', { name: /run scan/i })
    await user.click(button)
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /scanning/i })).toBeInTheDocument()
    })
  })

  it('button is disabled while scanning', async () => {
    server.use(
      http.get('/api/scanner/runs/:runId', () => HttpResponse.json(MOCK_RUN_PENDING))
    )
    const user = userEvent.setup()
    renderApp()
    const button = screen.getByRole('button', { name: /run scan/i })
    await user.click(button)
    await waitFor(() => {
      expect(button).toBeDisabled()
    })
  })

  it('shows error banner when scan POST fails', async () => {
    server.use(
      http.post('/api/scanner/run', () =>
        HttpResponse.json({ detail: 'No symbols in watchlist' }, { status: 422 })
      )
    )
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: /run scan/i }))
    await waitFor(() => {
      expect(screen.getByText(/HTTP 422/i)).toBeInTheDocument()
    })
  })

  it('clears scanning state when run status becomes completed', { timeout: 20_000 }, async () => {
    // First call returns pending, second returns completed
    let callCount = 0
    server.use(
      http.get('/api/scanner/runs/:runId', () => {
        callCount++
        return callCount === 1
          ? HttpResponse.json(MOCK_RUN_PENDING)
          : HttpResponse.json(MOCK_RUN_COMPLETED)
      })
    )
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: /run scan/i }))
    // Wait for scanning to start
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /scanning/i })).toBeInTheDocument()
    })
    // Wait for scan to complete and button to restore
    await waitFor(
      () => {
        expect(screen.getByRole('button', { name: /run scan/i })).not.toBeDisabled()
      },
      { timeout: 15_000 }
    )
  })

  it('shows error banner when run status is failed', async () => {
    server.use(
      http.get('/api/scanner/runs/:runId', () => HttpResponse.json(MOCK_RUN_FAILED))
    )
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: /run scan/i }))
    await waitFor(
      () => {
        expect(screen.getByText(/DB connection timeout/i)).toBeInTheDocument()
      },
      { timeout: 15_000 }
    )
  })

  it('shows "no results" message when scan completes with 0 scored symbols', async () => {
    server.use(
      http.get('/api/scanner/runs/:runId', () =>
        HttpResponse.json({ ...MOCK_RUN_COMPLETED, symbols_scored: 0, symbols_scanned: 5 })
      ),
      http.get('/api/scanner/results', () => HttpResponse.json([]))
    )
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: /run scan/i }))
    await waitFor(
      () => {
        expect(screen.getByText(/no results/i)).toBeInTheDocument()
      },
      { timeout: 15_000 }
    )
  })

  it('profile filter tabs are rendered', async () => {
    renderApp()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /all/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /momentum breakout/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /mean reversion/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /trend following/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /harmonic setup/i })).toBeInTheDocument()
  })

  it('clicking a profile tab triggers a filtered results fetch', async () => {
    let capturedUrl = ''
    server.use(
      http.get('/api/scanner/results', ({ request }) => {
        capturedUrl = request.url
        return HttpResponse.json(
          MOCK_RESULTS.filter((r) => r.profile_matches.includes('MomentumBreakout'))
        )
      })
    )
    const user = userEvent.setup()
    renderApp()
    await user.click(screen.getByRole('button', { name: /momentum breakout/i }))
    await waitFor(() => {
      expect(capturedUrl).toContain('profile=MomentumBreakout')
    })
  })

  it('shows "Failed to load results" when GET /scanner/results errors', async () => {
    server.use(
      http.get('/api/scanner/results', () => HttpResponse.error())
    )
    renderApp()
    await waitFor(
      () => {
        expect(screen.getByText(/failed to load results/i)).toBeInTheDocument()
      },
      { timeout: 5_000 }
    )
  })
})
