"""CLI: print brief stock info for a ticker symbol.

Usage:
    stonky-info AAPL
    stonky-info MSFT
"""

import argparse
import sys

from stonky.data import Quote, fetch_quote


def _print_quote(q: Quote) -> None:
    sign = "+" if q.change >= 0 else ""
    rows = [
        ("Company",  q.long_name),
        ("Exchange", f"{q.exchange}  ·  {q.currency}"),
        ("Price",    f"{q.last_price:.2f}"),
        ("Change",   f"{sign}{q.change:.2f}  ({sign}{q.change_pct:.2f}%)"),
        ("52w High", f"{q.year_high:.2f}"),
        ("52w Low",  f"{q.year_low:.2f}"),
    ]
    col = max(len(label) for label, _ in rows)
    print(f"\n  {q.symbol}")
    for label, value in rows:
        print(f"  {label:<{col}}  {value}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="stonky-info",
        description="Print brief stock info for a ticker symbol.",
    )
    parser.add_argument("symbol", help="Ticker symbol, e.g. AAPL")
    args = parser.parse_args()

    try:
        quote = fetch_quote(args.symbol.strip().upper())
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)

    _print_quote(quote)


if __name__ == "__main__":
    main()
