"""
Fetch recorded OHLCV snapshots for golden file tests.

Run this script ONCE to download real market data and save as CSVs.
The CSVs are committed to the repo and never fetched during tests.

Usage:
    python scripts/fetch_snapshots.py
"""

from __future__ import annotations

from pathlib import Path

import yfinance as yf

FIXTURES_DIR = Path(__file__).parent.parent / "backend" / "tests" / "fixtures" / "recorded"

SNAPSHOTS = [
    {
        "name": "aapl_2024_q1q2",
        "ticker": "AAPL",
        "start": "2024-01-02",
        "end": "2024-06-29",
        "interval": "1d",
    },
    {
        "name": "spy_2024_q1",
        "ticker": "SPY",
        "start": "2024-01-02",
        "end": "2024-03-29",
        "interval": "1d",
    },
]


def fetch_snapshot(config: dict) -> None:
    ticker = yf.Ticker(config["ticker"])
    df = ticker.history(
        start=config["start"],
        end=config["end"],
        interval=config["interval"],
        auto_adjust=False,
    )

    # Normalize columns
    df = df.reset_index()
    df = df.rename(
        columns={
            "Date": "time",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
            "Adj Close": "adj_close",
        }
    )
    df = df[["time", "open", "high", "low", "close", "volume", "adj_close"]]
    df["time"] = df["time"].dt.strftime("%Y-%m-%d")

    # Round to 4 decimal places for consistency
    for col in ["open", "high", "low", "close", "adj_close"]:
        df[col] = df[col].round(4)

    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    path = FIXTURES_DIR / f"{config['name']}.csv"
    df.to_csv(path, index=False)
    print(f"  Saved {len(df)} bars to {path}")


def main() -> None:
    print("Fetching recorded OHLCV snapshots...")
    for config in SNAPSHOTS:
        print(f"\n  {config['name']} ({config['ticker']} {config['start']} to {config['end']})")
        fetch_snapshot(config)
    print("\nDone. Commit the CSV files to the repo.")


if __name__ == "__main__":
    main()
