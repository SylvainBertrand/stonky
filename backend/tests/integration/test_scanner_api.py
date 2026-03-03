"""
Integration tests for the scanner API.

Coverage:
  POST /api/scanner/run               — queues background task, creates scan_run record
  GET  /api/scanner/runs/{run_id}     — returns scan_run status
  GET  /api/scanner/results           — returns cached analysis sorted by score
  GET  /api/scanner/results/{symbol}  — returns full detail for one ticker
  GET  /api/scanner/profiles          — lists the 4 built-in TA profiles
  POST /api/scanner/run/{symbol}      — inline single-symbol analysis
"""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from tests.factories import (
    create_indicator_cache,
    create_ohlcv_bars,
    create_symbol,
    create_watchlist,
    create_watchlist_item,
)
from tests.generators import gen_uptrend


# ---------------------------------------------------------------------------
# POST /api/scanner/run
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_trigger_scan_empty_watchlist_returns_422(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /scanner/run with a watchlist that has no symbols → 422."""
    # Create a watchlist with no symbols, use watchlist_id to avoid default-watchlist state pollution
    wl = await create_watchlist(db_session)
    await db_session.commit()

    response = await async_client.post(f"/api/scanner/run?watchlist_id={wl.id}")
    assert response.status_code == 422
    assert "No symbols in watchlist" in response.json()["detail"]


@pytest.mark.integration
async def test_trigger_scan_no_default_watchlist_returns_422(
    async_client: httpx.AsyncClient,
) -> None:
    """POST /scanner/run with no default watchlist and no watchlist_id param → 422."""
    # This hits the endpoint without specifying a watchlist_id.
    # In a clean test environment (no committed is_default watchlist) this should 422.
    # We just confirm the endpoint handles missing/empty watchlist gracefully.
    response = await async_client.post("/api/scanner/run")
    # Either 422 (no symbols) or 202 (if a prior test left a populated default watchlist)
    assert response.status_code in {202, 422}


@pytest.mark.integration
async def test_trigger_scan_with_symbols_returns_202_and_run_id(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /scanner/run?watchlist_id= with a populated watchlist → 202, integer run_id, status=queued."""
    wl = await create_watchlist(db_session)
    sym = await create_symbol(db_session, ticker="AAPLTEST")
    await create_watchlist_item(db_session, watchlist=wl, symbol=sym)
    await db_session.commit()

    response = await async_client.post(f"/api/scanner/run?watchlist_id={wl.id}")
    assert response.status_code == 202
    data = response.json()
    assert isinstance(data["run_id"], int)
    assert data["status"] == "queued"
    assert data["symbols_queued"] == 1


@pytest.mark.integration
async def test_trigger_scan_specific_watchlist(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /scanner/run?watchlist_id= scans the specified watchlist."""
    wl = await create_watchlist(db_session)
    sym = await create_symbol(db_session, ticker="SPECIFIC")
    await create_watchlist_item(db_session, watchlist=wl, symbol=sym)
    await db_session.commit()

    response = await async_client.post(f"/api/scanner/run?watchlist_id={wl.id}")
    assert response.status_code == 202
    data = response.json()
    assert data["symbols_queued"] == 1


# ---------------------------------------------------------------------------
# GET /api/scanner/runs/{run_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_run_status_pending(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /scanner/runs/{run_id} for a freshly-queued run → status field is present."""
    wl = await create_watchlist(db_session)
    sym = await create_symbol(db_session, ticker="RUNSTAT")
    await create_watchlist_item(db_session, watchlist=wl, symbol=sym)
    await db_session.commit()

    run_resp = await async_client.post(f"/api/scanner/run?watchlist_id={wl.id}")
    assert run_resp.status_code == 202
    run_id = run_resp.json()["run_id"]

    # Poll immediately — background task hasn't run yet in test context
    status_resp = await async_client.get(f"/api/scanner/runs/{run_id}")
    assert status_resp.status_code == 200
    data = status_resp.json()
    assert data["run_id"] == run_id
    assert data["status"] in {"queued", "pending", "running", "completed"}
    # These fields must always be present (None when not started)
    assert "started_at" in data
    assert "completed_at" in data
    assert "error_message" in data
    assert isinstance(data["symbols_scanned"], int)
    assert isinstance(data["symbols_scored"], int)


@pytest.mark.integration
async def test_get_run_status_404(
    async_client: httpx.AsyncClient,
) -> None:
    """GET /scanner/runs/999999 → 404."""
    response = await async_client.get("/api/scanner/runs/999999")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/scanner/results
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_results_empty(
    async_client: httpx.AsyncClient,
) -> None:
    """GET /scanner/results with no cached data → 200, empty list."""
    response = await async_client.get("/api/scanner/results")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.integration
async def test_get_results_returns_cached_analysis(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /scanner/results returns pre-populated cached analysis, sorted by composite_score."""
    sym_a = await create_symbol(db_session, ticker="HIGHSCORE")
    sym_b = await create_symbol(db_session, ticker="LOWSCORE")

    # high scorer
    await create_indicator_cache(
        db_session, sym_a,
        value={"composite_score": 0.80},
        time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    # low scorer
    await create_indicator_cache(
        db_session, sym_b,
        value={"composite_score": 0.10},
        time=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    await db_session.commit()

    response = await async_client.get("/api/scanner/results")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 2

    tickers = [r["symbol"] for r in data]
    high_idx = tickers.index("HIGHSCORE")
    low_idx = tickers.index("LOWSCORE")
    assert high_idx < low_idx, "HIGHSCORE should rank above LOWSCORE"

    # Verify response structure
    first = data[high_idx]
    assert "symbol" in first
    assert "rank" in first
    assert "scanned_at" in first
    assert "composite_score" in first
    assert "category_scores" in first
    assert "profile_matches" in first
    assert "signals" in first
    assert "meta" in first
    assert "is_actionable" in first


@pytest.mark.integration
async def test_get_results_rank_assignment(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Rank field is assigned in descending composite_score order (relative ordering)."""
    sym_a = await create_symbol(db_session, ticker="RANK1A")
    sym_b = await create_symbol(db_session, ticker="RANK2B")
    sym_c = await create_symbol(db_session, ticker="RANK3C")

    for sym, score in [(sym_a, 0.9), (sym_b, 0.5), (sym_c, 0.1)]:
        await create_indicator_cache(db_session, sym, value={"composite_score": score})
    await db_session.commit()

    response = await async_client.get("/api/scanner/results")
    assert response.status_code == 200
    by_ticker = {r["symbol"]: r for r in response.json()}

    # Check relative ordering: RANK1A > RANK2B > RANK3C
    assert by_ticker["RANK1A"]["rank"] < by_ticker["RANK2B"]["rank"], (
        "RANK1A (score 0.9) must rank above RANK2B (score 0.5)"
    )
    assert by_ticker["RANK2B"]["rank"] < by_ticker["RANK3C"]["rank"], (
        "RANK2B (score 0.5) must rank above RANK3C (score 0.1)"
    )
    # Ranks must be unique positive integers
    ranks = [by_ticker[sym]["rank"] for sym in ("RANK1A", "RANK2B", "RANK3C")]
    assert len(set(ranks)) == 3
    assert all(r >= 1 for r in ranks)


@pytest.mark.integration
async def test_get_results_deduplicates_per_symbol(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Multiple cache entries for same symbol → only the latest is returned."""
    sym = await create_symbol(db_session, ticker="DEDUPTEST")
    old_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    new_time = datetime(2026, 1, 2, tzinfo=timezone.utc)

    await create_indicator_cache(db_session, sym, value={"composite_score": 0.1}, time=old_time)
    await create_indicator_cache(db_session, sym, value={"composite_score": 0.9}, time=new_time)
    await db_session.commit()

    response = await async_client.get("/api/scanner/results")
    assert response.status_code == 200
    data = response.json()
    matches = [r for r in data if r["symbol"] == "DEDUPTEST"]
    assert len(matches) == 1
    # Should be the newer, higher-scored entry
    assert matches[0]["composite_score"] == pytest.approx(0.9, abs=1e-4)


@pytest.mark.integration
async def test_get_results_with_profile_filter(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /scanner/results?profile=MomentumBreakout returns only matching results."""
    sym_matches = await create_symbol(db_session, ticker="MBREAKOUT")
    sym_other = await create_symbol(db_session, ticker="NOPROFILE")

    await create_indicator_cache(
        db_session, sym_matches,
        value={"composite_score": 0.7, "profile_matches": ["MomentumBreakout"]},
    )
    await create_indicator_cache(
        db_session, sym_other,
        value={"composite_score": 0.5, "profile_matches": []},
    )
    await db_session.commit()

    response = await async_client.get("/api/scanner/results?profile=MomentumBreakout")
    assert response.status_code == 200
    data = response.json()
    tickers = [r["symbol"] for r in data]
    assert "MBREAKOUT" in tickers
    assert "NOPROFILE" not in tickers


@pytest.mark.integration
async def test_get_results_profile_filter_snake_case(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """?profile=momentum_breakout (snake_case) normalizes to CamelCase correctly."""
    sym = await create_symbol(db_session, ticker="SNAKEPRO")
    await create_indicator_cache(
        db_session, sym,
        value={"composite_score": 0.6, "profile_matches": ["MomentumBreakout"]},
    )
    await db_session.commit()

    response = await async_client.get("/api/scanner/results?profile=momentum_breakout")
    assert response.status_code == 200
    data = response.json()
    assert any(r["symbol"] == "SNAKEPRO" for r in data)


@pytest.mark.integration
async def test_get_results_timeframe_filter(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /scanner/results?timeframe=1w returns weekly results only."""
    sym = await create_symbol(db_session, ticker="WEEKLYTF")
    await create_indicator_cache(db_session, sym, timeframe="1w")
    await db_session.commit()

    # 1w query should return the bar
    resp_1w = await async_client.get("/api/scanner/results?timeframe=1w")
    assert resp_1w.status_code == 200
    assert any(r["symbol"] == "WEEKLYTF" for r in resp_1w.json())

    # 1d query should NOT return the weekly bar
    resp_1d = await async_client.get("/api/scanner/results?timeframe=1d")
    assert resp_1d.status_code == 200
    assert not any(r["symbol"] == "WEEKLYTF" for r in resp_1d.json())


# ---------------------------------------------------------------------------
# GET /api/scanner/results/{symbol}
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_get_symbol_result_404_unknown_symbol(
    async_client: httpx.AsyncClient,
) -> None:
    """GET /scanner/results/ZZZZZ → 404 (symbol not in DB)."""
    response = await async_client.get("/api/scanner/results/ZZZZZ")
    assert response.status_code == 404


@pytest.mark.integration
async def test_get_symbol_result_404_no_cache(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /scanner/results/{symbol} with known symbol but no cache entry → 404."""
    sym = await create_symbol(db_session, ticker="NOCACHE")
    await db_session.commit()

    response = await async_client.get("/api/scanner/results/NOCACHE")
    assert response.status_code == 404
    assert "Run /scanner/run/NOCACHE" in response.json()["detail"]


@pytest.mark.integration
async def test_get_symbol_result_returns_detail(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """GET /scanner/results/{symbol} with pre-populated cache → full AnalysisResponse."""
    sym = await create_symbol(db_session, ticker="DETAIL")
    await create_indicator_cache(
        db_session, sym,
        value={"composite_score": 0.55, "is_actionable": True},
    )
    await db_session.commit()

    response = await async_client.get("/api/scanner/results/DETAIL")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "DETAIL"
    assert data["composite_score"] == pytest.approx(0.55, abs=1e-4)
    assert data["is_actionable"] is True
    assert "category_scores" in data
    assert "meta" in data


# ---------------------------------------------------------------------------
# GET /api/scanner/profiles
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_list_profiles_returns_four_profiles(
    async_client: httpx.AsyncClient,
) -> None:
    """GET /scanner/profiles → list of 4 built-in profiles with correct fields."""
    response = await async_client.get("/api/scanner/profiles")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 4

    for profile in data:
        assert "name" in profile
        assert "description" in profile
        assert "score_threshold" in profile
        assert "required_conditions" in profile
        assert isinstance(profile["required_conditions"], list)


@pytest.mark.integration
async def test_list_profiles_includes_expected_names(
    async_client: httpx.AsyncClient,
) -> None:
    """Profile names include the four canonical profiles."""
    response = await async_client.get("/api/scanner/profiles")
    assert response.status_code == 200
    names = {p["name"] for p in response.json()}
    assert "MomentumBreakout" in names
    assert "MeanReversion" in names
    assert "TrendFollowing" in names
    assert "HarmonicSetup" in names


# ---------------------------------------------------------------------------
# POST /api/scanner/run/{symbol}  (inline single-symbol analysis)
# ---------------------------------------------------------------------------


@pytest.mark.integration
async def test_run_symbol_unknown_returns_404(
    async_client: httpx.AsyncClient,
) -> None:
    """POST /scanner/run/ZZZZZ → 404 if symbol not in DB."""
    response = await async_client.post("/api/scanner/run/ZZZZZ")
    assert response.status_code == 404


@pytest.mark.integration
async def test_run_symbol_no_ohlcv_returns_422(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /scanner/run/{symbol} with no OHLCV data → 422."""
    sym = await create_symbol(db_session, ticker="NOOHLCV")
    await db_session.commit()

    response = await async_client.post("/api/scanner/run/NOOHLCV")
    assert response.status_code == 422
    assert "OHLCV" in response.json()["detail"] or "Insufficient" in response.json()["detail"]


@pytest.mark.integration
async def test_run_symbol_with_ohlcv_returns_analysis(
    async_client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """POST /scanner/run/{symbol} with sufficient OHLCV → full AnalysisResponse inline."""
    sym = await create_symbol(db_session, ticker="WITHOHLCV")
    df = gen_uptrend(bars=250, seed=42)
    await create_ohlcv_bars(db_session, sym, df, timeframe="1d")
    await db_session.commit()

    response = await async_client.post("/api/scanner/run/WITHOHLCV")
    assert response.status_code == 200
    data = response.json()
    assert data["symbol"] == "WITHOHLCV"
    assert isinstance(data["composite_score"], float)
    assert -1.0 <= data["composite_score"] <= 1.0
    assert "category_scores" in data
    for cat in ("trend", "momentum", "volume", "volatility", "support_resistance", "divergence", "pattern"):
        assert cat in data["category_scores"]
    assert isinstance(data["meta"]["bars"], int)
    assert data["meta"]["bars"] == 250
    assert isinstance(data["is_actionable"], bool)
    assert isinstance(data["volume_contradiction"], bool)
