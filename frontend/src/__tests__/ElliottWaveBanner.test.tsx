import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ElliottWaveBanner } from '../components/stock/ElliottWaveBanner'
import type { EWDetection } from '../types'

const BULLISH_W3: EWDetection = {
  symbol: 'AAPL',
  wave_type: 'impulse',
  direction: 'bullish',
  current_position: 'wave_3',
  confidence: 0.82,
  waves: [],
}

const NO_WAVE: EWDetection = {
  symbol: 'AAPL',
  wave_type: null,
  direction: null,
  current_position: null,
  confidence: 0.0,
  waves: [],
}

describe('ElliottWaveBanner', () => {
  it('renders nothing when wave_type is null', () => {
    const { container } = render(<ElliottWaveBanner detection={NO_WAVE} />)
    expect(container.firstChild).toBeNull()
  })

  it('renders nothing when detection is undefined', () => {
    const { container } = render(<ElliottWaveBanner detection={undefined} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows Impulse label', () => {
    render(<ElliottWaveBanner detection={BULLISH_W3} />)
    expect(screen.getByText(/Impulse/i)).toBeInTheDocument()
  })

  it('shows Bullish direction badge', () => {
    render(<ElliottWaveBanner detection={BULLISH_W3} />)
    expect(screen.getByText(/Bullish/i)).toBeInTheDocument()
  })

  it('shows current wave position', () => {
    render(<ElliottWaveBanner detection={BULLISH_W3} />)
    expect(screen.getByText(/Wave 3/i)).toBeInTheDocument()
  })

  it('shows confidence as percentage', () => {
    render(<ElliottWaveBanner detection={BULLISH_W3} />)
    expect(screen.getByText(/82%/)).toBeInTheDocument()
  })

  it('shows Bearish for bearish direction', () => {
    const bearish: EWDetection = { ...BULLISH_W3, direction: 'bearish' }
    render(<ElliottWaveBanner detection={bearish} />)
    expect(screen.getByText(/Bearish/i)).toBeInTheDocument()
  })
})
