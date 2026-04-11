"""Async FRED API client for fetching economic data series."""

from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Series we fetch
FRED_SERIES = ["DGS10", "DGS2", "FEDFUNDS", "M2SL"]


def parse_fred_response(raw: dict[str, Any]) -> pd.DataFrame:
    """Parse FRED JSON response into a DataFrame with columns: date, value."""
    observations = raw.get("observations", [])
    if not observations:
        return pd.DataFrame(columns=["date", "value"])

    rows = []
    for obs in observations:
        val_str = obs.get("value", ".")
        value = None if val_str == "." else float(val_str)
        rows.append({"date": obs["date"], "value": value})

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


async def fetch_fred_series(
    series_id: str,
    api_key: str | None,
    observation_start: str,
) -> pd.DataFrame:
    """Fetch a FRED series. Returns empty DataFrame if key missing or request fails."""
    if not api_key:
        logger.warning("FRED_API_KEY not configured — skipping %s", series_id)
        return pd.DataFrame(columns=["date", "value"])

    params = {
        "series_id": series_id,
        "api_key": api_key,
        "observation_start": observation_start,
        "file_type": "json",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(FRED_BASE, params=params)
            resp.raise_for_status()
            return parse_fred_response(resp.json())
    except Exception:
        logger.exception("FRED fetch failed for %s", series_id)
        return pd.DataFrame(columns=["date", "value"])
