"""Tests for AAII/NAAIM sentiment parsing."""

from __future__ import annotations

from datetime import date

import pytest

from app.market.sentiment import (
    parse_aaii_csv,
    parse_naaim_csv,
)


@pytest.mark.unit
class TestParseAAIICsv:
    def test_valid_csv(self):
        csv_text = (
            "date,bullish,neutral,bearish\n2025-01-09,35.2,30.1,34.7\n2025-01-16,40.0,25.0,35.0\n"
        )
        results = parse_aaii_csv(csv_text)
        assert len(results) == 2
        assert results[0].week_ending == date(2025, 1, 9)
        assert results[0].bullish_pct == pytest.approx(35.2)
        assert results[0].bull_bear_spread == pytest.approx(0.5)  # 35.2 - 34.7

    def test_empty_csv(self):
        csv_text = "date,bullish,neutral,bearish\n"
        results = parse_aaii_csv(csv_text)
        assert len(results) == 0

    def test_malformed_csv_returns_empty(self):
        csv_text = "garbage,data\nno,sense\n"
        results = parse_aaii_csv(csv_text)
        assert len(results) == 0


@pytest.mark.unit
class TestParseNAAIMCsv:
    def test_valid_csv(self):
        csv_text = "date,exposure\n2025-01-08,72.5\n2025-01-15,68.3\n"
        results = parse_naaim_csv(csv_text)
        assert len(results) == 2
        assert results[0]["week_ending"] == date(2025, 1, 8)
        assert results[0]["exposure"] == pytest.approx(72.5)

    def test_empty_csv(self):
        csv_text = "date,exposure\n"
        results = parse_naaim_csv(csv_text)
        assert len(results) == 0
