"""Server-side candlestick chart rendering for YOLOv8 inference.

Renders clean 640x640 candlestick images using mplfinance — no labels, no grid,
no volume bars — optimized for pattern detection model input.
"""

from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# YOLOv8 standard input size
IMAGE_SIZE = 640
DEFAULT_BARS = 120


def render_chart_image(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "1d",
    bars: int = DEFAULT_BARS,
    output_path: Path | None = None,
) -> bytes | Path:
    """Render a clean candlestick chart image suitable for YOLOv8 inference.

    Parameters
    ----------
    df : pd.DataFrame
        OHLCV data with columns: open, high, low, close, volume.
        Must have a DatetimeIndex or a 'time' column.
    symbol : str
        Ticker symbol (for logging only).
    timeframe : str
        Timeframe label (for logging only).
    bars : int
        Number of bars to include in the chart (default 120 ~ 6 months daily).
    output_path : Path | None
        If provided, save the image to this path and return the Path.
        If None, return the image as bytes.

    Returns
    -------
    bytes | Path
        Image data as PNG bytes, or the output file path if output_path was given.
    """
    import matplotlib
    matplotlib.use("Agg")
    import mplfinance as mpf

    chart_df = df.copy()

    # Ensure we have at most `bars` bars
    if len(chart_df) > bars:
        chart_df = chart_df.tail(bars).reset_index(drop=True)

    # mplfinance requires a DatetimeIndex
    if "time" in chart_df.columns:
        chart_df["time"] = pd.to_datetime(chart_df["time"], utc=True)
        chart_df = chart_df.set_index("time")
    elif not isinstance(chart_df.index, pd.DatetimeIndex):
        chart_df.index = pd.to_datetime(chart_df.index)

    # Ensure required columns exist
    for col in ("open", "high", "low", "close"):
        if col not in chart_df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Custom style: black background, green/red candles, no grid
    mc = mpf.make_marketcolors(
        up="lime",
        down="red",
        edge="inherit",
        wick="inherit",
        volume="in",
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        facecolor="black",
        edgecolor="black",
        figcolor="black",
        gridstyle="",
        gridcolor="black",
        y_on_right=False,
    )

    # Compute figure size in inches for 640x640px at 100 DPI
    dpi = 100
    fig_size = (IMAGE_SIZE / dpi, IMAGE_SIZE / dpi)

    buf = io.BytesIO()
    mpf.plot(
        chart_df,
        type="candle",
        style=style,
        volume=False,
        axisoff=True,
        tight_layout=True,
        figsize=fig_size,
        savefig=dict(fname=buf, dpi=dpi, bbox_inches="tight", pad_inches=0),
    )
    buf.seek(0)
    image_bytes = buf.read()

    log.info(
        "Rendered chart for %s (%s): %d bars, %d bytes",
        symbol,
        timeframe,
        len(chart_df),
        len(image_bytes),
    )

    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(image_bytes)
        return output_path

    return image_bytes
