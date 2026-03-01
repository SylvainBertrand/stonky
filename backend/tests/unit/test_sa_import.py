"""Unit tests for app.ingestion.sa_import (no DB, no network)."""
from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from app.ingestion.sa_import import (
    _parse_float,
    _parse_grade,
    _parse_int,
    _find_column,
    parse_sa_spreadsheet,
)
from app.models.enums import SALetterGrade


# ---------------------------------------------------------------------------
# _parse_grade
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        ("A+", SALetterGrade.A_PLUS),
        ("A", SALetterGrade.A),
        ("B+", SALetterGrade.B_PLUS),
        ("B-", SALetterGrade.B_MINUS),
        ("F", SALetterGrade.F),
        ("D-", SALetterGrade.D_MINUS),
    ],
)
def test_parse_grade_valid(value: str, expected: SALetterGrade) -> None:
    assert _parse_grade(value) == expected


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, "", "  ", "N/A", "nan", float("nan")])
def test_parse_grade_none_on_missing(value: object) -> None:
    assert _parse_grade(value) is None


@pytest.mark.unit
def test_parse_grade_unknown_string_returns_none() -> None:
    assert _parse_grade("Z") is None


# ---------------------------------------------------------------------------
# _parse_float
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "value,expected",
    [
        ("3.75", 3.75),
        ("4.00", 4.0),
        (3.5, 3.5),
        ("3.5%", 0.035),
        ("0%", 0.0),
        ("100%", 1.0),
    ],
)
def test_parse_float_valid(value: object, expected: float) -> None:
    result = _parse_float(value)
    assert result is not None
    assert result == pytest.approx(expected, rel=1e-6)


@pytest.mark.unit
@pytest.mark.parametrize("value", [None, "", "  ", float("nan")])
def test_parse_float_none_on_missing(value: object) -> None:
    assert _parse_float(value) is None


@pytest.mark.unit
def test_parse_float_non_numeric_returns_none() -> None:
    assert _parse_float("n/a") is None


# ---------------------------------------------------------------------------
# _parse_int
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_parse_int_valid() -> None:
    assert _parse_int("5") == 5
    assert _parse_int(10) == 10
    assert _parse_int("3.7") == 3


@pytest.mark.unit
def test_parse_int_none_on_missing() -> None:
    assert _parse_int(None) is None
    assert _parse_int(float("nan")) is None


# ---------------------------------------------------------------------------
# _find_column
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_find_column_exact_match() -> None:
    df = pd.DataFrame(columns=["Ticker", "Quant Rating", "Momentum"])
    assert _find_column(df, ["ticker", "symbol"]) == "Ticker"


@pytest.mark.unit
def test_find_column_case_insensitive() -> None:
    df = pd.DataFrame(columns=["TICKER", "GROWTH"])
    assert _find_column(df, ["ticker"]) == "TICKER"


@pytest.mark.unit
def test_find_column_space_normalized() -> None:
    df = pd.DataFrame(columns=["Quant Rating"])
    assert _find_column(df, ["quant_rating", "quant rating"]) == "Quant Rating"


@pytest.mark.unit
def test_find_column_returns_none_when_not_found() -> None:
    df = pd.DataFrame(columns=["Open", "Close"])
    assert _find_column(df, ["ticker", "symbol"]) is None


# ---------------------------------------------------------------------------
# parse_sa_spreadsheet
# ---------------------------------------------------------------------------


def _write_csv(content: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False)
    tmp.write(content)
    tmp.flush()
    tmp.close()
    return Path(tmp.name)


@pytest.mark.unit
def test_parse_sa_spreadsheet_minimal_csv() -> None:
    csv = "Ticker,Quant Rating,Momentum\nAAPL,4.5,A\nMSFT,3.8,B+\n"
    p = _write_csv(csv)
    try:
        df = parse_sa_spreadsheet(p)
        assert list(df["ticker"]) == ["AAPL", "MSFT"]
        assert "quant_score" in df.columns
        assert "momentum_grade" in df.columns
    finally:
        p.unlink(missing_ok=True)


@pytest.mark.unit
def test_parse_sa_spreadsheet_tickers_uppercased() -> None:
    csv = "ticker,Quant Rating\naapl,4.0\nmsft,3.5\n"
    p = _write_csv(csv)
    try:
        df = parse_sa_spreadsheet(p)
        assert all(t == t.upper() for t in df["ticker"])
    finally:
        p.unlink(missing_ok=True)


@pytest.mark.unit
def test_parse_sa_spreadsheet_blank_rows_dropped() -> None:
    csv = "Ticker,Quant Rating\nAAPL,4.0\n,\nMSFT,3.5\n"
    p = _write_csv(csv)
    try:
        df = parse_sa_spreadsheet(p)
        assert len(df) == 2
    finally:
        p.unlink(missing_ok=True)


@pytest.mark.unit
def test_parse_sa_spreadsheet_missing_ticker_raises() -> None:
    csv = "Open,Close\n100,105\n"
    p = _write_csv(csv)
    try:
        with pytest.raises(ValueError, match="ticker"):
            parse_sa_spreadsheet(p)
    finally:
        p.unlink(missing_ok=True)


@pytest.mark.unit
def test_parse_sa_spreadsheet_grade_columns_present() -> None:
    csv = "Ticker,Valuation,Growth,Profitability,Momentum,EPS Revisions\n"
    csv += "AAPL,A+,B,A-,B+,C\n"
    p = _write_csv(csv)
    try:
        df = parse_sa_spreadsheet(p)
        for col in ("valuation_grade", "growth_grade", "profitability_grade", "momentum_grade", "eps_revision_grade"):
            assert col in df.columns, f"{col} should be in result"
    finally:
        p.unlink(missing_ok=True)


@pytest.mark.unit
def test_parse_sa_spreadsheet_unknown_columns_dropped() -> None:
    csv = "Ticker,SomeRandomCol,Quant Rating\nAAPL,xyz,4.0\n"
    p = _write_csv(csv)
    try:
        df = parse_sa_spreadsheet(p)
        assert "somerandomcol" not in df.columns
    finally:
        p.unlink(missing_ok=True)
