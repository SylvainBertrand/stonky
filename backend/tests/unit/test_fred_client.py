"""Tests for FRED API client."""

from __future__ import annotations

import pandas as pd
import pytest

from app.market.fred_client import fetch_fred_series, parse_fred_response


@pytest.mark.unit
class TestParseFredResponse:
    def test_valid_response(self):
        raw = {
            "observations": [
                {"date": "2025-01-02", "value": "4.25"},
                {"date": "2025-01-03", "value": "4.30"},
            ]
        }
        df = parse_fred_response(raw)
        assert len(df) == 2
        assert list(df.columns) == ["date", "value"]
        assert df.iloc[0]["value"] == pytest.approx(4.25)

    def test_missing_value_dot(self):
        raw = {
            "observations": [
                {"date": "2025-01-02", "value": "."},
                {"date": "2025-01-03", "value": "4.30"},
            ]
        }
        df = parse_fred_response(raw)
        assert len(df) == 2
        assert pd.isna(df.iloc[0]["value"])
        assert df.iloc[1]["value"] == pytest.approx(4.30)

    def test_empty_observations(self):
        raw = {"observations": []}
        df = parse_fred_response(raw)
        assert len(df) == 0
        assert list(df.columns) == ["date", "value"]

    def test_no_observations_key(self):
        raw = {"error": "bad request"}
        df = parse_fred_response(raw)
        assert len(df) == 0


@pytest.mark.unit
class TestFetchFredSeries:
    @pytest.mark.asyncio
    async def test_no_api_key_returns_empty(self):
        df = await fetch_fred_series("DGS10", api_key=None, observation_start="2025-01-01")
        assert len(df) == 0
        assert list(df.columns) == ["date", "value"]
