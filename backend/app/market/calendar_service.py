"""
NYSE market calendar service.

Pure computation — no I/O, no DB. Uses `pandas_market_calendars` for accurate
NYSE holiday handling. Public entry point: `get_market_status(now=None)`.

Session windows (NYSE local time, ET):
    pre-market   04:00 – 09:29
    regular      09:30 – 15:59
    after-hours  16:00 – 19:59
    closed       20:00 – 03:59  + weekends + NYSE holidays
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import pandas_market_calendars as mcal

NYSE_TZ_NAME = "America/New_York"
NYSE_TZ = ZoneInfo(NYSE_TZ_NAME)

# Singleton calendar (cheap to build, but no need to rebuild per request).
_NYSE = mcal.get_calendar("NYSE")

# Session boundaries in NYSE local time.
_PREMARKET_OPEN = time(4, 0)
_REGULAR_OPEN = time(9, 30)
_REGULAR_CLOSE = time(16, 0)
_AFTERHOURS_CLOSE = time(20, 0)

# How far ahead to look when finding the next open/close. 14 days easily covers
# the longest US market holiday gap (Thanksgiving + weekend, Christmas week).
_LOOKAHEAD_DAYS = 14


SessionLiteral = str  # "pre-market" | "regular" | "after-hours" | "closed"


@dataclass(frozen=True)
class MarketStatus:
    """Snapshot of NYSE market session state."""

    is_open: bool
    session: SessionLiteral
    next_open: datetime  # tz-aware UTC
    next_close: datetime  # tz-aware UTC
    timezone: str = NYSE_TZ_NAME


def _classify_session(now_et: datetime, is_trading_day: bool) -> tuple[SessionLiteral, bool]:
    """Return (session_label, is_open) for an ET-localized datetime."""
    if not is_trading_day:
        return "closed", False

    t = now_et.time()
    if t < _PREMARKET_OPEN:
        return "closed", False
    if t < _REGULAR_OPEN:
        return "pre-market", False
    if t < _REGULAR_CLOSE:
        return "regular", True
    if t < _AFTERHOURS_CLOSE:
        return "after-hours", False
    return "closed", False


def get_market_status(now: datetime | None = None) -> MarketStatus:
    """
    Compute the current NYSE market session status.

    Args:
        now: Override the wall-clock time (for testing). MUST be timezone-aware
            if provided. When None, uses real wall-clock time in UTC.

    Returns:
        `MarketStatus` with `is_open`, `session`, `next_open`, `next_close`,
        and `timezone`. `next_open`/`next_close` are tz-aware UTC datetimes
        representing the next regular-session boundaries strictly after `now`.
    """
    if now is None:
        now = datetime.now(tz=UTC)
    elif now.tzinfo is None:
        raise ValueError("`now` must be timezone-aware")

    now_utc = now.astimezone(UTC)
    now_et = now.astimezone(NYSE_TZ)

    # Pull the schedule for today + lookahead window. The DataFrame is indexed
    # by date (in UTC) with `market_open` / `market_close` UTC columns.
    schedule = _NYSE.schedule(
        start_date=now_et.date(),
        end_date=(now_et + timedelta(days=_LOOKAHEAD_DAYS)).date(),
    )

    today_et_date = now_et.date()
    is_trading_day = any(idx.date() == today_et_date for idx in schedule.index)

    session, is_open = _classify_session(now_et, is_trading_day)

    next_open: datetime | None = None
    next_close: datetime | None = None
    for _, row in schedule.iterrows():
        # market_open / market_close are pandas Timestamps in UTC.
        market_open_utc: datetime = pd.Timestamp(row["market_open"]).to_pydatetime()
        market_close_utc: datetime = pd.Timestamp(row["market_close"]).to_pydatetime()

        if next_open is None and market_open_utc > now_utc:
            next_open = market_open_utc
        if next_close is None and market_close_utc > now_utc:
            next_close = market_close_utc
        if next_open is not None and next_close is not None:
            break

    if next_open is None or next_close is None:
        # Should never happen — 14 days of lookahead always contains trading days.
        raise RuntimeError(
            f"Could not determine next NYSE open/close within {_LOOKAHEAD_DAYS} days "
            f"of {now_utc.isoformat()}"
        )

    return MarketStatus(
        is_open=is_open,
        session=session,
        next_open=next_open,
        next_close=next_close,
        timezone=NYSE_TZ_NAME,
    )
