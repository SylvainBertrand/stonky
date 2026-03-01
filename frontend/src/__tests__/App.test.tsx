import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../App'

describe('App', () => {
  it('renders the Stonky header', () => {
    render(<App />)
    expect(screen.getByText('Stonky')).toBeInTheDocument()
    expect(screen.getByText('Investment analysis platform')).toBeInTheDocument()
  })

  it('shows loading state initially', () => {
    render(<App />)
    expect(screen.getByText(/checking backend/i)).toBeInTheDocument()
  })

  it('shows health status after API response', async () => {
    render(<App />)
    // MSW intercepts /api/health and returns { status: 'ok', db: 'connected' }
    const statusBadge = await screen.findByText('ok')
    expect(statusBadge).toBeInTheDocument()

    const dbBadge = await screen.findByText('connected')
    expect(dbBadge).toBeInTheDocument()
  })

  it('shows system status section', () => {
    render(<App />)
    expect(screen.getByText(/system status/i)).toBeInTheDocument()
  })
})
