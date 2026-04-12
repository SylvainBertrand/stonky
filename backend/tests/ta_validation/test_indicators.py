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
    df["macd"] = macd_df.iloc[:, 0]  # MACD line
    df["macd_signal"] = macd_df.iloc[:, 1]  # Signal line
    df["macd_hist"] = macd_df.iloc[:, 2]  # Histogram

    values = _df_to_golden_values(df, ["macd", "macd_signal", "macd_hist"])

    assert_golden(
        indicator_name=f"macd_12_26_9_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "macd", "fast": 12, "slow": 26, "signal": 9},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# EMA-21, EMA-50, EMA-200
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker,length",
    [
        ("aapl_2024_q1q2.csv", "AAPL", 21),
        ("aapl_2024_q1q2.csv", "AAPL", 50),
        ("aapl_2024_q1q2.csv", "AAPL", 200),
    ],
)
async def test_ema_lengths(
    snapshot_file: str,
    ticker: str,
    length: int,
    update_golden: bool,
) -> None:
    """EMA-{length} output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()
    col = f"ema_{length}"
    df[col] = ta.ema(df["close"], length=length)
    values = _df_to_golden_values(df, [col])
    assert_golden(
        indicator_name=f"ema_{length}_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "ema", "length": length},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# ADX-14
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_adx_14(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """ADX-14 output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()
    result = ta.adx(df["high"], df["low"], df["close"], length=14)
    assert result is not None
    # Normalise column names to lowercase
    col_map = {}
    for c in result.columns:
        if c.startswith("ADX_"):
            col_map[c] = "adx_14"
        elif c.startswith("DMP_"):
            col_map[c] = "dmp_14"
        elif c.startswith("DMN_"):
            col_map[c] = "dmn_14"
    result = result.rename(columns=col_map)
    for col in ("adx_14", "dmp_14", "dmn_14"):
        if col in result.columns:
            df[col] = result[col]
    values = _df_to_golden_values(df, ["adx_14", "dmp_14", "dmn_14"])
    assert_golden(
        indicator_name=f"adx_14_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "adx", "length": 14},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# Supertrend
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_supertrend(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """Supertrend(10, 3.0) output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()
    result = ta.supertrend(df["high"], df["low"], df["close"], length=10, multiplier=3.0)
    assert result is not None
    dir_col = next((c for c in result.columns if c.startswith("SUPERTd_")), None)
    val_col = next(
        (
            c
            for c in result.columns
            if c.startswith("SUPERT_") and "d" not in c and "s" not in c.lower()
        ),
        None,
    )
    if dir_col:
        df["supertrend_dir"] = result[dir_col]
    if val_col:
        df["supertrend_val"] = result[val_col]
    out_cols = [c for c in ("supertrend_dir", "supertrend_val") if c in df.columns]
    values = _df_to_golden_values(df, out_cols)
    assert_golden(
        indicator_name=f"supertrend_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "supertrend", "length": 10, "multiplier": 3.0},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# Bollinger Bands (20, 2)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_bbands_20(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """Bollinger Bands(20, 2.0) output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()
    result = ta.bbands(df["close"], length=20, std=2.0)
    assert result is not None
    col_map = {}
    for c in result.columns:
        if c.startswith("BBL_"):
            col_map[c] = "bb_lower"
        elif c.startswith("BBM_"):
            col_map[c] = "bb_mid"
        elif c.startswith("BBU_"):
            col_map[c] = "bb_upper"
        elif c.startswith("BBP_"):
            col_map[c] = "bb_pct"
    result = result.rename(columns=col_map)
    for col in ("bb_lower", "bb_mid", "bb_upper", "bb_pct"):
        if col in result.columns:
            df[col] = result[col]
    values = _df_to_golden_values(df, ["bb_lower", "bb_mid", "bb_upper", "bb_pct"])
    assert_golden(
        indicator_name=f"bbands_20_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "bbands", "length": 20, "std": 2.0},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# ATR-14
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_atr_14(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """ATR-14 output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()
    df["atr_14"] = ta.atr(df["high"], df["low"], df["close"], length=14)
    values = _df_to_golden_values(df, ["atr_14"])
    assert_golden(
        indicator_name=f"atr_14_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "atr", "length": 14},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# Stochastic (14, 3, 3)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_stochastic(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """Stochastic(14, 3, 3) output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()
    result = ta.stoch(df["high"], df["low"], df["close"], k=14, d=3, smooth_k=3)
    assert result is not None
    col_map = {}
    for c in result.columns:
        if c.startswith("STOCHk_"):
            col_map[c] = "stoch_k"
        elif c.startswith("STOCHd_"):
            col_map[c] = "stoch_d"
    result = result.rename(columns=col_map)
    for col in ("stoch_k", "stoch_d"):
        if col in result.columns:
            df[col] = result[col]
    values = _df_to_golden_values(df, ["stoch_k", "stoch_d"])
    assert_golden(
        indicator_name=f"stoch_14_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "stoch", "k": 14, "d": 3, "smooth_k": 3},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# OBV
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_obv(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """OBV output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()
    df["obv"] = ta.obv(df["close"], df["volume"])
    values = _df_to_golden_values(df, ["obv"])
    assert_golden(
        indicator_name=f"obv_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "obv"},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )


# ---------------------------------------------------------------------------
# CMF-20
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "snapshot_file,ticker",
    [
        ("aapl_2024_q1q2.csv", "AAPL"),
    ],
)
async def test_cmf_20(
    snapshot_file: str,
    ticker: str,
    update_golden: bool,
) -> None:
    """CMF-20 output matches golden file."""
    df = _load_snapshot(snapshot_file)
    df = df.copy()
    df["cmf_20"] = ta.cmf(df["high"], df["low"], df["close"], df["volume"], length=20)
    values = _df_to_golden_values(df, ["cmf_20"])
    assert_golden(
        indicator_name=f"cmf_20_{ticker.lower()}",
        actual_values=values,
        update_mode=update_golden,
        params={"indicator": "cmf", "length": 20},
        snapshot=snapshot_file.replace(".csv", ""),
        tolerance=1e-4,
    )
