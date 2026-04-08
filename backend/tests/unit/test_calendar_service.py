"""
Unit tests for app.market.calendar_service.

Pure offline tests — `get_market_status` accepts an injected `now` parameter so
we can freeze time without monkeypatching `datetime.now`. Test fixture dates
were verified live against `pandas_market_calendars` for the NYSE calendar.
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from app.market.calendar_service import (
    NYSE_TZ_NAME,
    MarketStatus,
    get_market_status,
)

pytestmark = pytest.mark.unit

ET = ZoneInfo(NYSE_TZ_NAME)


def _et(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    """Build a tz-aware Eastern Time datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=ET)


# ── Session classification ───────────────────────────────────────────────────


def test_regular_hours_tuesday_10am_et() -> None:
    # Tuesday 2026-04-07 10:00 ET — confirmed trading day
    status = get_market_status(_et(2026, 4, 7, 10, 0))
    assert status.is_open is True
    assert status.session == "regular"
    assert status.timezone == NYSE_TZ_NAME


def test_pre_market_tuesday_7am_et() -> None:
    status = get_market_status(_et(2026, 4, 7, 7, 0))
    assert status.is_open is False
    assert status.session == "pre-market"


def test_after_hours_tuesday_5pm_et() -> None:
    status = get_market_status(_et(2026, 4, 7, 17, 0))
    assert status.is_open is False
    assert status.session == "after-hours"


def test_late_night_closed_tuesday_9pm_et() -> None:
    status = get_market_status(_et(2026, 4, 7, 21, 0))
    assert status.is_open is False
    assert status.session == "closed"


def test_early_morning_closed_tuesday_3am_et() -> None:
    # Just before pre-market opens at 04:00 ET
    status = get_market_status(_et(2026, 4, 7, 3, 0))
    assert status.is_open is False
    assert status.session == "closed"


# ── Boundary times ───────────────────────────────────────────────────────────


def test_premarket_boundary_4am_et_is_pre_market() -> None:
    # 04:00 ET sharp → pre-market begins
    status = get_market_status(_et(2026, 4, 7, 4, 0))
    assert status.session == "pre-market"


def test_regular_boundary_930am_et_is_regular() -> None:
    status = get_market_status(_et(2026, 4, 7, 9, 30))
    assert status.session == "regular"
    assert status.is_open is True


def test_regular_close_4pm_et_is_after_hours() -> None:
    # 16:00 ET → market closes, after-hours begins
    status = get_market_status(_et(2026, 4, 7, 16, 0))
    assert status.session == "after-hours"
    assert status.is_open is False


def test_after_hours_close_8pm_et_is_closed() -> None:
    status = get_market_status(_et(2026, 4, 7, 20, 0))
    assert status.session == "closed"


# ── Weekends + holidays ──────────────────────────────────────────────────────


def test_saturday_is_closed() -> None:
    # Saturday 2026-04-04 10:00 ET
    status = get_market_status(_et(2026, 4, 4, 10, 0))
    assert status.is_open is False
    assert status.session == "closed"


def test_sunday_is_closed() -> None:
    status = get_market_status(_et(2026, 4, 5, 10, 0))
    assert status.is_open is False
    assert status.session == "closed"


def test_good_friday_is_closed() -> None:
    # 2026-04-03 is Good Friday — NYSE closed
    status = get_market_status(_et(2026, 4, 3, 10, 0))
    assert status.is_open is False
    assert status.session == "closed"


def test_christmas_is_closed() -> None:
    # 2026-12-25 (Friday) — Christmas
    status = get_market_status(_et(2026, 12, 25, 10, 0))
    assert status.is_open is False
    assert status.session == "closed"


def test_thanksgiving_is_closed() -> None:
    # 2026-11-26 (Thursday) — Thanksgiving
    status = get_market_status(_et(2026, 11, 26, 10, 0))
    assert status.is_open is False
    assert status.session == "closed"


# ── next_open / next_close progression ───────────────────────────────────────


def test_next_open_during_pre_market_is_today_regular_open() -> None:
    # Tuesday 7am ET → next open is Tuesday 9:30am ET = 13:30 UTC (DST)
    status = get_market_status(_et(2026, 4, 7, 7, 0))
    assert status.next_open == datetime(2026, 4, 7, 13, 30, tzinfo=UTC)
    assert status.next_close == datetime(2026, 4, 7, 20, 0, tzinfo=UTC)


def test_next_open_during_regular_session_is_next_trading_day() -> None:
    # Tuesday 10am ET → next open is Wednesday 9:30am ET; close is today 4pm ET
    status = get_market_status(_et(2026, 4, 7, 10, 0))
    assert status.next_open == datetime(2026, 4, 8, 13, 30, tzinfo=UTC)
    assert status.next_close == datetime(2026, 4, 7, 20, 0, tzinfo=UTC)


def test_next_open_after_hours_is_next_trading_day() -> None:
    # Tuesday 17:00 ET → both next_open and next_close roll to Wednesday
    status = get_market_status(_et(2026, 4, 7, 17, 0))
    assert status.next_open == datetime(2026, 4, 8, 13, 30, tzinfo=UTC)
    assert status.next_close == datetime(2026, 4, 8, 20, 0, tzinfo=UTC)


def test_next_open_on_friday_after_close_is_monday() -> None:
    # Friday 2026-04-10 17:00 ET → next open is Monday 2026-04-13 9:30am ET
    status = get_market_status(_et(2026, 4, 10, 17, 0))
    assert status.next_open == datetime(2026, 4, 13, 13, 30, tzinfo=UTC)
    assert status.next_close == datetime(2026, 4, 13, 20, 0, tzinfo=UTC)


def test_next_open_during_holiday_skips_to_next_trading_day() -> None:
    # Good Friday 2026-04-03 10:00 ET → market closed; next open is Monday 04-06
    status = get_market_status(_et(2026, 4, 3, 10, 0))
    assert status.next_open == datetime(2026, 4, 6, 13, 30, tzinfo=UTC)
    assert status.next_close == datetime(2026, 4, 6, 20, 0, tzinfo=UTC)


# ── Input validation + return type ───────────────────────────────────────────


def test_naive_datetime_raises() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        get_market_status(datetime(2026, 4, 7, 10, 0))


def test_default_now_returns_status() -> None:
    # Should not raise; just smoke-test the live wall-clock path.
    status = get_market_status()
    assert isinstance(status, MarketStatus)
    assert status.session in {"pre-market", "regular", "after-hours", "closed"}


def test_accepts_utc_input_and_converts_to_et() -> None:
    # 14:00 UTC Tuesday 2026-04-07 == 10:00 ET (DST in effect)
    status = get_market_status(
        datetime(2026, 4, 7, 14, 0, tzinfo=UTC)
    )
    assert status.session == "regular"
    assert status.is_open is True
