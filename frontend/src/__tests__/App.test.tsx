import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import App from '../App'

describe('App', () => {
  it('renders the scanner page at root route', () => {
    render(<App />)
    expect(screen.getByText('Stonky')).toBeInTheDocument()
  })

  it('renders Run Scan button', () => {
    render(<App />)
    expect(screen.getByRole('button', { name: /run scan/i })).toBeInTheDocument()
  })
})
