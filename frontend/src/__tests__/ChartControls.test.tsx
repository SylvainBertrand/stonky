import { render, screen, fireEvent } from '@testing-library/react'
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { ChartControls, DEFAULT_OVERLAYS } from '../components/stock/ChartControls'
import type { OverlayToggles } from '../components/stock/ChartControls'

const ALL_ON: OverlayToggles = {
  ema21: true,
  ema50: true,
  ema200: true,
  supertrend: true,
  volume: true,
  patterns: true,
}

const ALL_OFF: OverlayToggles = {
  ema21: false,
  ema50: false,
  ema200: false,
  supertrend: false,
  volume: false,
  patterns: false,
}

describe('ChartControls', () => {
  let onToggle: ReturnType<typeof vi.fn>
  let onReset: ReturnType<typeof vi.fn>

  beforeEach(() => {
    onToggle = vi.fn()
    onReset = vi.fn()
  })

  // ── Rendering ────────────────────────────────────────────────────────────

  it('renders all 6 overlay toggle buttons', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    expect(screen.getByRole('button', { name: /ema 21/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /ema 50/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /ema 200/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /supertrend/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /volume/i })).toBeTruthy()
    expect(screen.getByRole('button', { name: /patterns/i })).toBeTruthy()
  })

  it('renders a Reset button', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    expect(screen.getByRole('button', { name: /reset/i })).toBeTruthy()
  })

  // ── aria-pressed ─────────────────────────────────────────────────────────

  it('toggle buttons have aria-pressed="true" when overlay is on', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    const btn = screen.getByRole('button', { name: /ema 21/i })
    expect(btn.getAttribute('aria-pressed')).toBe('true')
  })

  it('toggle buttons have aria-pressed="false" when overlay is off', () => {
    render(<ChartControls overlays={ALL_OFF} onToggle={onToggle} onReset={onReset} />)
    const btn = screen.getByRole('button', { name: /ema 21/i })
    expect(btn.getAttribute('aria-pressed')).toBe('false')
  })

  it('each button aria-pressed reflects its individual state', () => {
    const mixed: OverlayToggles = { ...ALL_OFF, ema21: true, supertrend: true }
    render(<ChartControls overlays={mixed} onToggle={onToggle} onReset={onReset} />)
    expect(screen.getByRole('button', { name: /ema 21/i }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: /ema 50/i }).getAttribute('aria-pressed')).toBe('false')
    expect(screen.getByRole('button', { name: /supertrend/i }).getAttribute('aria-pressed')).toBe('true')
    expect(screen.getByRole('button', { name: /volume/i }).getAttribute('aria-pressed')).toBe('false')
  })

  // ── Callbacks ────────────────────────────────────────────────────────────

  it('calls onToggle with "ema21" when EMA 21 button is clicked', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /ema 21/i }))
    expect(onToggle).toHaveBeenCalledWith('ema21')
  })

  it('calls onToggle with "ema50" when EMA 50 button is clicked', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /ema 50/i }))
    expect(onToggle).toHaveBeenCalledWith('ema50')
  })

  it('calls onToggle with "ema200" when EMA 200 button is clicked', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /ema 200/i }))
    expect(onToggle).toHaveBeenCalledWith('ema200')
  })

  it('calls onToggle with "supertrend" when Supertrend button is clicked', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /supertrend/i }))
    expect(onToggle).toHaveBeenCalledWith('supertrend')
  })

  it('calls onToggle with "volume" when Volume button is clicked', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /volume/i }))
    expect(onToggle).toHaveBeenCalledWith('volume')
  })

  it('calls onToggle with "patterns" when Patterns button is clicked', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /patterns/i }))
    expect(onToggle).toHaveBeenCalledWith('patterns')
  })

  it('calls onToggle exactly once per click', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /ema 21/i }))
    expect(onToggle).toHaveBeenCalledTimes(1)
  })

  it('calls onReset when Reset button is clicked', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /reset/i }))
    expect(onReset).toHaveBeenCalledTimes(1)
  })

  it('does not call onToggle when Reset is clicked', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    fireEvent.click(screen.getByRole('button', { name: /reset/i }))
    expect(onToggle).not.toHaveBeenCalled()
  })

  // ── EMA colored dots ─────────────────────────────────────────────────────

  it('EMA 21 button contains a blue dot', () => {
    const { container } = render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    const btn = screen.getByRole('button', { name: /ema 21/i })
    const dot = btn.querySelector('[data-dot]')
    expect(dot).toBeTruthy()
    expect((dot as HTMLElement).style.backgroundColor).toBe('rgb(59, 130, 246)')
  })

  it('EMA 50 button contains an orange dot', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    const btn = screen.getByRole('button', { name: /ema 50/i })
    const dot = btn.querySelector('[data-dot]')
    expect(dot).toBeTruthy()
    expect((dot as HTMLElement).style.backgroundColor).toBe('rgb(249, 115, 22)')
  })

  it('EMA 200 button contains a gray dot', () => {
    render(<ChartControls overlays={ALL_ON} onToggle={onToggle} onReset={onReset} />)
    const btn = screen.getByRole('button', { name: /ema 200/i })
    const dot = btn.querySelector('[data-dot]')
    expect(dot).toBeTruthy()
    expect((dot as HTMLElement).style.backgroundColor).toBe('rgb(107, 114, 128)')
  })

  it('renders the EW Waves toggle button', () => {
    const overlays = { ...DEFAULT_OVERLAYS, waves: true } as OverlayToggles
    render(<ChartControls overlays={overlays} onToggle={vi.fn()} onReset={vi.fn()} />)
    expect(screen.getByRole('button', { name: /EW Waves/i })).toBeInTheDocument()
  })

  it('fires onToggle with "waves" when EW Waves button clicked', () => {
    const onToggle = vi.fn()
    const overlays = { ...DEFAULT_OVERLAYS, waves: true } as OverlayToggles
    render(<ChartControls overlays={overlays} onToggle={onToggle} onReset={vi.fn()} />)
    fireEvent.click(screen.getByRole('button', { name: /EW Waves/i }))
    expect(onToggle).toHaveBeenCalledWith('waves')
  })
})
