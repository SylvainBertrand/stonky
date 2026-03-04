"""
Smoke tests: full scanner pipeline on committed real-world market data.

Flow under test:
  CSV snapshot → DB insert → POST /scanner/run/{symbol} → GET /scanner/results/{symbol}

Verifies that the end-to-end path produces structurally valid, directionally
sensible results against actual AAPL and SPY price history.

Snapshots live in tests/fixtures/recorded/ and are committed to the repo.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pandas as pd
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import create_ohlcv_bars, create_symbol

pytestmark = pytest.mark.integration

_RECORDED_DIR = Path(__file__).parent.parent / "fixtures" / "recorded"

_SEVEN_CATEGORIES = frozenset(
    {"trend", "momentum", "volume", "volatility", "support_resistance", "divergence", "pattern"}
)


def _load_snapshot(filename: str) -> pd.DataFrame:
    path = _RECORDED_DIR / filename
    if not path.exists():
        pytest.skip(f"Snapshot not found: {path}. Run scripts/fetch_snapshots.py")
    return pd.read_csv(path, parse_dates=["time"])


# ---------------------------------------------------------------------------
# Structural integrity (both tickers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file, ticker, expected_bars",
    [
        ("aapl_2024_q1q2.csv", "SMKAAPL", 124),
        ("spy_2024_q1.csv", "SMKSPY", 61),
    ],
)
async def test_real_data_scan_structure(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
    snapshot_file: str,
    ticker: str,
    expected_bars: int,
) -> None:
    """POST /scanner/run/{symbol} on real market data returns a structurally valid 200 response."""
    df = _load_snapshot(snapshot_file)
    sym = await create_symbol(db_session, ticker=ticker)
    await create_ohlcv_bars(db_session, sym, df, timeframe="1d")
    await db_session.commit()

    response = await async_client.post(f"/api/scanner/run/{ticker}")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    data = response.json()
    assert data["symbol"] == ticker

    # Composite score in range
    score = data["composite_score"]
    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0, f"composite_score {score} out of [-1, 1]"

    # All 7 categories present and in range
    cats = data["category_scores"]
    assert set(cats.keys()) == _SEVEN_CATEGORIES, f"Missing categories: {_SEVEN_CATEGORIES - set(cats.keys())}"
    for cat, cat_score in cats.items():
        assert -1.0 <= cat_score <= 1.0, f"category {cat}={cat_score} out of range"

    # Meta sanity
    meta = data["meta"]
    assert meta["bars"] == expected_bars, f"Expected {expected_bars} bars, got {meta['bars']}"
    assert meta["last_price"] > 0
    assert meta["atr"] > 0
    assert meta["atr_pct"] > 0

    # Last price must match the final close in the snapshot
    expected_last_close = float(df["close"].iloc[-1])
    assert meta["last_price"] == pytest.approx(expected_last_close, rel=1e-4), (
        f"last_price {meta['last_price']} doesn't match CSV close {expected_last_close}"
    )

    # Signals non-trivial
    signals = data["signals"]
    assert len(signals) >= 6, f"Expected at least 6 signals, got {len(signals)}: {list(signals)}"
    assert "rsi" in signals, "Expected 'rsi' in signals"
    for sig_name, sig_val in signals.items():
        assert -1.0 <= sig_val <= 1.0, f"signal {sig_name}={sig_val} out of range"

    assert isinstance(data["is_actionable"], bool)
    assert isinstance(data["volume_contradiction"], bool)


# ---------------------------------------------------------------------------
# Profile matching on real data
# ---------------------------------------------------------------------------


async def test_real_data_aapl_matches_momentum_breakout(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """AAPL Q1+Q2 2024 has strong trend + volume; must match MomentumBreakout profile."""
    df = _load_snapshot("aapl_2024_q1q2.csv")
    sym = await create_symbol(db_session, ticker="SMKMBAAPL")
    await create_ohlcv_bars(db_session, sym, df, timeframe="1d")
    await db_session.commit()

    response = await async_client.post("/api/scanner/run/SMKMBAAPL")
    assert response.status_code == 200, response.text

    data = response.json()
    assert "MomentumBreakout" in data["profile_matches"], (
        f"Expected MomentumBreakout in profile_matches, got {data['profile_matches']}. "
        f"composite={data['composite_score']:.4f}, "
        f"category_scores={data['category_scores']}"
    )


# ---------------------------------------------------------------------------
# Cache persistence
# ---------------------------------------------------------------------------


async def test_real_data_result_cached_after_scan(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /scanner/results/{symbol} must return the same score as the inline scan just run."""
    df = _load_snapshot("aapl_2024_q1q2.csv")
    sym = await create_symbol(db_session, ticker="SMKCACHE")
    await create_ohlcv_bars(db_session, sym, df, timeframe="1d")
    await db_session.commit()

    scan_resp = await async_client.post("/api/scanner/run/SMKCACHE")
    assert scan_resp.status_code == 200, scan_resp.text

    get_resp = await async_client.get("/api/scanner/results/SMKCACHE")
    assert get_resp.status_code == 200, get_resp.text

    inline = scan_resp.json()
    cached = get_resp.json()
    assert cached["symbol"] == "SMKCACHE"
    assert cached["composite_score"] == pytest.approx(inline["composite_score"], abs=1e-4)
    assert set(cached["category_scores"].keys()) == _SEVEN_CATEGORIES


# ---------------------------------------------------------------------------
# Directional sanity: SPY gained ~11 % in Q1 2024
# ---------------------------------------------------------------------------


async def test_real_data_spy_q1_2024_bullish(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """SPY Q1 2024 was a clear uptrend (+11%); trend or momentum category must be positive."""
    df = _load_snapshot("spy_2024_q1.csv")
    sym = await create_symbol(db_session, ticker="SMKBULL")
    await create_ohlcv_bars(db_session, sym, df, timeframe="1d")
    await db_session.commit()

    response = await async_client.post("/api/scanner/run/SMKBULL")
    assert response.status_code == 200, response.text

    data = response.json()
    cats = data["category_scores"]
    assert cats["trend"] > 0 or cats["momentum"] > 0, (
        f"SPY Q1 2024 (+11%): expected positive trend or momentum, got {cats}"
    )
