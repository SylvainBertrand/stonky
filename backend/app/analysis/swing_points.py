"""
Swing point detection — shared infrastructure.

Used by: Fibonacci retracement, divergence detection, anchored VWAP, S/R clustering.
Compute once; cache in `swing_points` table.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.signal import argrelextrema


def detect_swing_points(
    series: pd.Series,
    order: int = 5,
    atr_filter: float = 0.5,
    atr_series: pd.Series | None = None,
) -> tuple[pd.Series, pd.Series]:
    """
    Detect swing highs and swing lows in a price series.

    Uses scipy.signal.argrelextrema for local max/min detection, then applies
    an optional ATR filter to reject noise: the swing size must be >= atr_filter * ATR.

    Parameters
    ----------
    series : pd.Series
        Price values (typically close or high/low).
    order : int
        Number of bars on each side required for a local extremum.
    atr_filter : float
        Minimum swing size as a multiple of ATR. 0 = no filter.
    atr_series : pd.Series | None
        ATR values aligned to `series`. Required when atr_filter > 0.

    Returns
    -------
    (swing_highs, swing_lows) : tuple[pd.Series, pd.Series]
        Boolean Series aligned to `series.index`.
        True at each confirmed swing high / swing low.
    """
    n = len(series)
    swing_highs = pd.Series(False, index=series.index)
    swing_lows = pd.Series(False, index=series.index)

    if n < 2 * order + 1:
        return swing_highs, swing_lows

    arr = series.to_numpy()

    high_idxs = argrelextrema(arr, np.greater_equal, order=order)[0]
    low_idxs = argrelextrema(arr, np.less_equal, order=order)[0]

    if atr_filter > 0.0 and atr_series is not None:
        atr_arr = atr_series.to_numpy()

        filtered_highs = []
        for i in high_idxs:
            # Compare to nearest preceding low
            prev_lows = low_idxs[low_idxs < i]
            if len(prev_lows) == 0:
                filtered_highs.append(i)
                continue
            prev_low_idx = prev_lows[-1]
            swing_size = abs(arr[i] - arr[prev_low_idx])
            atr_val = atr_arr[i] if not np.isnan(atr_arr[i]) else 0.0
            if atr_val == 0.0 or swing_size >= atr_filter * atr_val:
                filtered_highs.append(i)
        high_idxs = np.array(filtered_highs, dtype=int)

        filtered_lows = []
        for i in low_idxs:
            prev_highs = high_idxs[high_idxs < i]
            if len(prev_highs) == 0:
                filtered_lows.append(i)
                continue
            prev_high_idx = prev_highs[-1]
            swing_size = abs(arr[prev_high_idx] - arr[i])
            atr_val = atr_arr[i] if not np.isnan(atr_arr[i]) else 0.0
            if atr_val == 0.0 or swing_size >= atr_filter * atr_val:
                filtered_lows.append(i)
        low_idxs = np.array(filtered_lows, dtype=int)

    if len(high_idxs) > 0:
        swing_highs.iloc[high_idxs] = True
    if len(low_idxs) > 0:
        swing_lows.iloc[low_idxs] = True

    return swing_highs, swing_lows
