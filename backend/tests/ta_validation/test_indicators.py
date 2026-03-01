"""
Golden file comparison tests for TA indicators.

Run normally:      pytest tests/ta_validation/ -v
Regenerate golden: pytest tests/ta_validation/ --update-golden -v

Golden files live in tests/fixtures/golden/{indicator_name}.json
Recorded snapshots live in tests/fixtures/recorded/*.csv
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import pandas_ta as ta
import pytest

from tests.golden_plugin import assert_golden

_FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
_RECORDED_DIR = _FIXTURES_DIR / "recorded"

pytestmark = pytest.mark.ta_validation


def _load_snapshot(filename: str) -> pd.DataFrame:
    path = _RECORDED_DIR / filename
    if not path.exists():
        pytest.skip(f"Recorded snapshot not found: {path}. Run scripts/fetch_snapshots.py")
    df = pd.read_csv(path, parse_dates=["time"])
    return df


def _df_to_golden_values(df: pd.DataFrame, value_cols: list[str]) -> list[dict[str, Any]]:
    """Convert indicator output DataFrame to the golden file format."""
    records: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        entry: dict[str, Any] = {"time": str(row["time"].date())}
        for col in value_cols:
            val = row.get(col)
            if pd.isna(val):
                entry[col] = None
            else:
                entry[col] = round(float(val), 8)
        records.append(entry)
    return records


# ---------------------------------------------------------------------------
# RSI-14
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_rsi_14(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """RSI-14 output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()

    # Compute RSI-14 via pandas-ta
    rsi_series = ta.rsi(df["close"], length=14)
    df["rsi"] = rsi_series

    values = _df_to_golden_values(df, ["rsi"])

    assert_golden(
        indicator_name=f"rsi_14_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "rsi", "length": 14},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# EMA-20
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_ema_20(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """EMA-20 output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()

    ema_series = ta.ema(df["close"], length=20)
    df["ema"] = ema_series

    values = _df_to_golden_values(df, ["ema"])

    assert_golden(
        indicator_name=f"ema_20_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "ema", "length": 20},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# MACD (12, 26, 9)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_macd(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """MACD(12,26,9) output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()

    macd_df = ta.macd(df["close"], fast=12, slow=26, signal=9)
    assert macd_df is not None
    df["macd"] = macd_df.iloc[:, 0]      # MACD line
    df["macd_signal"] = macd_df.iloc[:, 1]  # Signal line
    df["macd_hist"] = macd_df.iloc[:, 2]   # Histogram

    values = _df_to_golden_values(df, ["macd", "macd_signal", "macd_hist"])

    assert_golden(
        indicator_name=f"macd_12_26_9_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "macd", "fast": 12, "slow": 26, "signal": 9},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )
