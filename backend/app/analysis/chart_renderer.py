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


def _prepare_chart_df(df: pd.DataFrame, bars: int) -> pd.DataFrame:
    """Trim to last `bars` bars and ensure DatetimeIndex."""
    chart_df = df.copy()
    if len(chart_df) > bars:
        chart_df = chart_df.tail(bars).reset_index(drop=True)
    if "time" in chart_df.columns:
        chart_df["time"] = pd.to_datetime(chart_df["time"], utc=True)
        chart_df = chart_df.set_index("time")
    elif not isinstance(chart_df.index, pd.DatetimeIndex):
        chart_df.index = pd.to_datetime(chart_df.index)
    for col in ("open", "high", "low", "close"):
        if col not in chart_df.columns:
            raise ValueError(f"Missing required column: {col}")
    return chart_df


def _make_mpf_style() -> object:
    """Return the mplfinance style for YOLO chart rendering."""
    import mplfinance as mpf

    mc = mpf.make_marketcolors(
        up="lime",
        down="red",
        edge="inherit",
        wick="inherit",
        volume="in",
    )
    return mpf.make_mpf_style(
        marketcolors=mc,
        facecolor="black",
        edgecolor="black",
        figcolor="black",
        gridstyle="",
        gridcolor="black",
        y_on_right=False,
    )


def render_chart_image_with_price_range(
    df: pd.DataFrame,
    symbol: str,
    timeframe: str = "1d",
    bars: int = DEFAULT_BARS,
) -> tuple[bytes, float, float]:
    """Render chart image and return (image_bytes, price_min, price_max).

    price_min / price_max are the actual y-axis limits used by mplfinance
    (includes auto-scaling margin beyond raw OHLCV data).  These are needed
    to convert normalized YOLO bbox y-coordinates back to price space.
    """
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import mplfinance as mpf

    chart_df = _prepare_chart_df(df, bars)
    style = _make_mpf_style()
    dpi = 100
    fig_size = (IMAGE_SIZE / dpi, IMAGE_SIZE / dpi)

    buf = io.BytesIO()
    fig, axes = mpf.plot(
        chart_df,
        type="candle",
        style=style,
        volume=False,
        axisoff=True,
        tight_layout=True,
        figsize=fig_size,
        savefig=dict(fname=buf, dpi=dpi, bbox_inches="tight", pad_inches=0),
        returnfig=True,
    )

    ax = axes[0]
    price_min, price_max = ax.get_ylim()
    plt.close(fig)

    buf.seek(0)
    image_bytes = buf.read()

    log.info(
        "Rendered chart for %s (%s): %d bars, %d bytes, price_range=[%.4f, %.4f]",
        symbol,
        timeframe,
        len(chart_df),
        len(image_bytes),
        price_min,
        price_max,
    )
    return image_bytes, price_min, price_max


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

    chart_df = _prepare_chart_df(df, bars)
    style = _make_mpf_style()
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
