"""Backend: data fetching and domain types.

All yfinance access lives here. The UI layer imports only StockData,
fetch_stock_data, fetch_quote, and load_portfolio, so the backend is
fully testable without a display.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import yfinance as yf


@dataclass
class Quote:
    """Lightweight real-time snapshot for a single ticker."""
    symbol: str
    long_name: str
    exchange: str
    currency: str
    last_price: float
    previous_close: float
    year_high: float
    year_low: float

    @property
    def change(self) -> float:
        return self.last_price - self.previous_close

    @property
    def change_pct(self) -> float:
        if not self.previous_close:
            return 0.0
        return self.change / self.previous_close * 100


def fetch_quote(symbol: str) -> Quote:
    """Fetch a lightweight real-time quote for *symbol*.

    Uses fast_info (no full history download) so it is much faster than
    fetch_stock_data.

    Raises:
        ValueError: if the symbol is not found or has no price data.
    """
    ticker = yf.Ticker(symbol)
    fast_info = ticker.fast_info

    last_price = getattr(fast_info, "last_price", None)
    if last_price is None:
        raise ValueError(f'No data found for "{symbol}". Check the symbol.')

    try:
        info = ticker.info
        long_name = info.get("longName") or info.get("shortName") or symbol
    except Exception:
        long_name = symbol

    prev_close = getattr(fast_info, "regular_market_previous_close", None) or last_price

    return Quote(
        symbol=symbol,
        long_name=long_name,
        exchange=getattr(fast_info, "exchange", "—"),
        currency=getattr(fast_info, "currency", "USD"),
        last_price=last_price,
        previous_close=prev_close,
        year_high=getattr(fast_info, "year_high", 0.0) or 0.0,
        year_low=getattr(fast_info, "year_low", 0.0) or 0.0,
    )


@dataclass
class StockData:
    """All data needed to render a stock chart."""
    symbol: str
    period: str
    history: pd.DataFrame  # OHLCV — columns: Open, High, Low, Close, Volume
    long_name: str
    exchange: str
    currency: str


def fetch_stock_data(symbol: str, period: str) -> StockData:
    """Fetch price history and metadata for *symbol* over *period*.

    Raises:
        ValueError: if no data is available for the symbol.
    """
    ticker = yf.Ticker(symbol)
    history = ticker.history(period=period)

    if history.empty:
        raise ValueError(f'No data found for "{symbol}". Check the symbol.')

    fast_info = ticker.fast_info
    try:
        info = ticker.info
        long_name = info.get("longName") or info.get("shortName") or symbol
    except Exception:
        long_name = symbol

    return StockData(
        symbol=symbol,
        period=period,
        history=history,
        long_name=long_name,
        exchange=getattr(fast_info, "exchange", "—"),
        currency=getattr(fast_info, "currency", "USD"),
    )


def load_portfolio(path: str | Path) -> list[str]:
    """Load ticker symbols from a CSV file with a 'symbol' column.

    Symbols are uppercased, whitespace-trimmed, and deduplicated (preserving
    first occurrence order). Empty rows are skipped.

    Raises:
        FileNotFoundError: if *path* does not exist.
        ValueError: if the CSV has no 'symbol' column.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Portfolio file not found: {path}")

    symbols: list[str] = []
    seen: set[str] = set()

    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        raw_fields = reader.fieldnames or []
        lower_fields = [f.strip().lower() for f in raw_fields]
        if "symbol" not in lower_fields:
            raise ValueError(f"'{path}' has no 'symbol' column.")
        symbol_field = raw_fields[lower_fields.index("symbol")]

        for row in reader:
            raw = row.get(symbol_field, "") or ""
            sym = raw.strip().upper()
            if sym and sym not in seen:
                seen.add(sym)
                symbols.append(sym)

    return symbols
