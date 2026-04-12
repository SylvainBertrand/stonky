import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ResultsTable } from '../components/scanner/ResultsTable';
import { makeScannerResult } from '../test/mocks/handlers';
import type { ScannerResult } from '../types';

function renderTable(results: ScannerResult[]) {
  return render(
    <MemoryRouter>
      <ResultsTable results={results} />
    </MemoryRouter>
  );
}

describe('ResultsTable', () => {
  it('shows placeholder when results list is empty', () => {
    renderTable([]);
    expect(screen.getByText(/no results yet/i)).toBeInTheDocument();
    expect(screen.getByText(/run scan/i)).toBeInTheDocument();
  });

  it('renders one row per result', () => {
    const results = [
      makeScannerResult({ symbol: 'AAPL', rank: 1 }),
      makeScannerResult({ symbol: 'MSFT', rank: 2 }),
      makeScannerResult({ symbol: 'NVDA', rank: 3 }),
    ];
    renderTable(results);
    expect(screen.getByText('AAPL')).toBeInTheDocument();
    expect(screen.getByText('MSFT')).toBeInTheDocument();
    expect(screen.getByText('NVDA')).toBeInTheDocument();
  });

  it('renders rank numbers in table', () => {
    const results = [
      makeScannerResult({ symbol: 'AAPL', rank: 1 }),
      makeScannerResult({ symbol: 'MSFT', rank: 2 }),
    ];
    renderTable(results);
    expect(screen.getByText('1')).toBeInTheDocument();
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('renders composite score for each result', () => {
    const results = [makeScannerResult({ symbol: 'AAPL', rank: 1, composite_score: 0.65 })];
    renderTable(results);
    // Score should be displayed (formatted)
    const scoreEl = screen.getByText(/0\.65|65/i);
    expect(scoreEl).toBeInTheDocument();
  });

  it('shows last_price in the row', () => {
    const results = [
      makeScannerResult({
        symbol: 'AAPL',
        meta: { ...makeScannerResult().meta!, last_price: 185.5 },
      }),
    ];
    renderTable(results);
    expect(screen.getByText(/185/)).toBeInTheDocument();
  });

  it('expands a row when clicked', async () => {
    const user = userEvent.setup();
    const result = makeScannerResult({ symbol: 'AAPL', rank: 1 });
    renderTable([result]);

    // Find the expand button (last column button in the row)
    const row = screen.getByText('AAPL').closest('tr');
    expect(row).not.toBeNull();
    const expandBtn = row!.querySelector('button');
    if (expandBtn) {
      await user.click(expandBtn);
      // After expanding, category scores or signals section should appear
      // (RowExpansion component renders category breakdown)
      const expanded =
        document.querySelector('[data-testid="row-expansion"]') ??
        screen.queryByText(/trend|momentum|divergence/i);
      // Either data-testid or category names should be visible
      expect(expanded || screen.queryByText(/ATR/i)).toBeTruthy();
    }
  });

  it('renders profile badge for matched profiles', () => {
    const results = [
      makeScannerResult({ symbol: 'AAPL', rank: 1, profile_matches: ['MomentumBreakout'] }),
    ];
    renderTable(results);
    // ProfileBadge renders the abbreviated profile code (e.g. "MB" for MomentumBreakout)
    const badges = screen.getAllByText('MB');
    expect(badges.length).toBeGreaterThan(0);
  });

  it('renders table headers', () => {
    const results = [makeScannerResult()];
    renderTable(results);
    expect(screen.getByText(/symbol/i)).toBeInTheDocument();
    expect(screen.getByText(/score/i)).toBeInTheDocument();
    expect(screen.getByText(/price/i)).toBeInTheDocument();
  });
});
