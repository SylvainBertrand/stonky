"""Portfolio Monitor engine — pure functions for the 6 in-scope checks.

All functions are stateless and side-effect-free. They accept only primitive
types and are trivially unit-testable without mocks or DB fixtures.

Implements checks exactly as specified in briefs/portfolio-monitor.yaml v2.0.0
and workflow prompt 03 v1.1.0:

  CHECK-01  STOP_PROXIMITY      — position within 2% of stop
  CHECK-02  TARGET_PROXIMITY    — position within 2% of target
  CHECK-03  STOP_BREACH         — stop level crossed
  CHECK-03  TARGET_BREACH       — target level crossed
  CHECK-04  CONCENTRATION_RISK  — single >10% of portfolio or sector >30%
  CHECK-05  CORRELATION_RISK    — same sector+industry pair heuristic
  CHECK-07  STALE               — open >5 trading days (excl. weekends+holidays)

Check 6 (THESIS_DRIFT) is out of scope — moved to weekly research mode.

References:
  - Brief: briefs/portfolio-monitor.yaml v2.0.0
  - Ticket: TC-008 Acceptance Criteria #2, #3, #9
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Enums / Constants
# ---------------------------------------------------------------------------

STOP_PROXIMITY_THRESHOLD = 0.02  # 2% — brief CHECK-01
TARGET_PROXIMITY_THRESHOLD = 0.02  # 2% — brief CHECK-02
SINGLE_POSITION_PCT_THRESHOLD = 10.0  # 10% of portfolio — brief CHECK-04
SECTOR_PCT_THRESHOLD = 30.0  # 30% of portfolio — brief CHECK-04
STALE_TRADING_DAYS = 5  # brief CHECK-07

# US market holidays (approximate; covers NYSE holidays through 2027)
# Using a hardcoded set is consistent with "hand-roll if no market calendar lib"
# but pandas_market_calendars IS available (used by calendar_service.py) — use it.
_NYSE_CAL: Any | None = None


def _get_nyse_calendar() -> Any:
    global _NYSE_CAL
    if _NYSE_CAL is None:
        import pandas_market_calendars as mcal

        _NYSE_CAL = mcal.get_calendar("NYSE")
    return _NYSE_CAL


class FlagType(str, Enum):
    STOP_PROXIMITY = "STOP_PROXIMITY"
    TARGET_PROXIMITY = "TARGET_PROXIMITY"
    STOP_BREACH = "STOP_BREACH"
    TARGET_BREACH = "TARGET_BREACH"
    CONCENTRATION_RISK = "CONCENTRATION_RISK"
    CORRELATION_RISK = "CORRELATION_RISK"
    STALE = "STALE"
    DATA_MISSING = "DATA_MISSING"


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Flag:
    """A single check finding for one position."""

    flag_type: FlagType
    ticker: str
    severity: Severity
    description: str
    extra: dict[str, Any] = field(default_factory=dict)
    position_url: str = ""


# ---------------------------------------------------------------------------
# CHECK-01: STOP_PROXIMITY
# ---------------------------------------------------------------------------


def check_stop_proximity(
    *,
    ticker: str,
    current_price: float,
    stop: float,
    direction: str,
    position_url: str = "",
) -> Flag | None:
    """Flag positions within 2% of their stop level.

    Long:  (current_price - stop) / stop <= 0.02
    Short: (stop - current_price) / stop <= 0.02
    """
    if stop <= 0:
        return None
    if direction == "long":
        distance_pct = (current_price - stop) / stop
    else:
        distance_pct = (stop - current_price) / stop

    if distance_pct <= STOP_PROXIMITY_THRESHOLD:
        pct_display = distance_pct * 100
        return Flag(
            flag_type=FlagType.STOP_PROXIMITY,
            ticker=ticker,
            severity=Severity.WARNING,
            description=(
                f"{ticker} is {pct_display:.2f}% from stop (stop=${stop:.2f}, "
                f"current=${current_price:.2f}, direction={direction})"
            ),
            extra={"distance_pct": distance_pct, "stop": stop, "current_price": current_price},
            position_url=position_url,
        )
    return None


# ---------------------------------------------------------------------------
# CHECK-02: TARGET_PROXIMITY
# ---------------------------------------------------------------------------


def check_target_proximity(
    *,
    ticker: str,
    current_price: float,
    target: float,
    direction: str,
    position_url: str = "",
) -> Flag | None:
    """Flag positions within 2% of their target level.

    Long:  (target - current_price) / target <= 0.02
    Short: (current_price - target) / target <= 0.02
    """
    if target <= 0:
        return None
    if direction == "long":
        distance_pct = (target - current_price) / target
    else:
        distance_pct = (current_price - target) / target

    if distance_pct <= TARGET_PROXIMITY_THRESHOLD:
        pct_display = distance_pct * 100
        return Flag(
            flag_type=FlagType.TARGET_PROXIMITY,
            ticker=ticker,
            severity=Severity.INFO,
            description=(
                f"{ticker} is {pct_display:.2f}% from target (target=${target:.2f}, "
                f"current=${current_price:.2f}, direction={direction})"
            ),
            extra={"distance_pct": distance_pct, "target": target, "current_price": current_price},
            position_url=position_url,
        )
    return None


# ---------------------------------------------------------------------------
# CHECK-03: STOP_BREACH / TARGET_BREACH
# ---------------------------------------------------------------------------


def check_breach(
    *,
    ticker: str,
    current_price: float,
    stop: float,
    target: float,
    direction: str,
    position_url: str = "",
) -> list[Flag]:
    """Detect stop or target level crossings. Returns 0, 1, or 2 flags.

    Priority: stop checked before target (matches paper_trader engine logic).

    Long:
      stop_breach:   current_price <= stop
      target_breach: current_price >= target
    Short:
      stop_breach:   current_price >= stop
      target_breach: current_price <= target
    """
    flags: list[Flag] = []

    if direction == "long":
        if current_price <= stop:
            flags.append(
                Flag(
                    flag_type=FlagType.STOP_BREACH,
                    ticker=ticker,
                    severity=Severity.CRITICAL,
                    description=(
                        f"{ticker} STOP BREACH: current=${current_price:.2f} <= stop=${stop:.2f}"
                    ),
                    extra={"current_price": current_price, "stop": stop},
                    position_url=position_url,
                )
            )
        if current_price >= target:
            flags.append(
                Flag(
                    flag_type=FlagType.TARGET_BREACH,
                    ticker=ticker,
                    severity=Severity.CRITICAL,
                    description=(
                        f"{ticker} TARGET BREACH: current=${current_price:.2f} >= target=${target:.2f}"
                    ),
                    extra={"current_price": current_price, "target": target},
                    position_url=position_url,
                )
            )
    else:  # short
        if current_price >= stop:
            flags.append(
                Flag(
                    flag_type=FlagType.STOP_BREACH,
                    ticker=ticker,
                    severity=Severity.CRITICAL,
                    description=(
                        f"{ticker} STOP BREACH (short): current=${current_price:.2f} >= stop=${stop:.2f}"
                    ),
                    extra={"current_price": current_price, "stop": stop},
                    position_url=position_url,
                )
            )
        if current_price <= target:
            flags.append(
                Flag(
                    flag_type=FlagType.TARGET_BREACH,
                    ticker=ticker,
                    severity=Severity.CRITICAL,
                    description=(
                        f"{ticker} TARGET BREACH (short): current=${current_price:.2f} <= target=${target:.2f}"
                    ),
                    extra={"current_price": current_price, "target": target},
                    position_url=position_url,
                )
            )

    return flags


# ---------------------------------------------------------------------------
# CHECK-04: CONCENTRATION_RISK
# ---------------------------------------------------------------------------


def check_concentration_risk(
    positions: list[dict[str, Any]],
    prices: dict[str, float],
) -> list[Flag]:
    """Flag single-position >10% or sector >30% of portfolio.

    Args:
        positions: List of position dicts (from get_open_positions).
        prices: {ticker: current_price} mapping.

    Returns list of CONCENTRATION_RISK flags.
    """
    flags: list[Flag] = []
    if not positions:
        return flags

    # Compute position market values
    position_values: dict[str, float] = {}
    for pos in positions:
        ticker = pos["ticker"]
        price = prices.get(ticker, pos.get("current_price", 0.0))
        size = pos.get("size", 0.0)
        position_values[ticker] = price * size

    total_value = sum(position_values.values())
    if total_value <= 0:
        return flags

    # Single-position check (>10%)
    for pos in positions:
        ticker = pos["ticker"]
        val = position_values.get(ticker, 0.0)
        pct = (val / total_value) * 100
        if pct > SINGLE_POSITION_PCT_THRESHOLD:
            flags.append(
                Flag(
                    flag_type=FlagType.CONCENTRATION_RISK,
                    ticker=ticker,
                    severity=Severity.WARNING,
                    description=(
                        f"{ticker} concentration {pct:.1f}% exceeds "
                        f"{SINGLE_POSITION_PCT_THRESHOLD}% threshold"
                    ),
                    extra={"position_pct": pct, "threshold": SINGLE_POSITION_PCT_THRESHOLD},
                    position_url=pos.get("url", ""),
                )
            )

    # Sector check (>30%)
    sector_values: dict[str, float] = {}
    for pos in positions:
        sector = pos.get("sector", "") or "Unknown"
        ticker = pos["ticker"]
        sector_values[sector] = sector_values.get(sector, 0.0) + position_values.get(ticker, 0.0)

    for sector, val in sector_values.items():
        pct = (val / total_value) * 100
        if pct > SECTOR_PCT_THRESHOLD:
            flags.append(
                Flag(
                    flag_type=FlagType.CONCENTRATION_RISK,
                    ticker="PORTFOLIO",
                    severity=Severity.WARNING,
                    description=(
                        f"Sector '{sector}' concentration {pct:.1f}% exceeds "
                        f"{SECTOR_PCT_THRESHOLD}% threshold"
                    ),
                    extra={"sector": sector, "sector_pct": pct, "threshold": SECTOR_PCT_THRESHOLD},
                )
            )

    return flags


# ---------------------------------------------------------------------------
# CHECK-05: CORRELATION_RISK
# ---------------------------------------------------------------------------


def check_correlation_risk(positions: list[dict[str, Any]]) -> list[Flag]:
    """Flag pairs of positions in the same sector AND same industry.

    Phase 1 heuristic: same sector + same industry = correlated.
    Phase 2 (deferred): quantitative correlation matrix.
    """
    flags: list[Flag] = []
    if len(positions) < 2:
        return flags

    # Group by (sector, industry)
    from collections import defaultdict

    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pos in positions:
        sector = (pos.get("sector") or "").strip()
        industry = (pos.get("industry") or "").strip()
        if sector and industry:
            groups[(sector, industry)].append(pos)

    for (sector, industry), group in groups.items():
        if len(group) >= 2:
            tickers = [p["ticker"] for p in group]
            flags.append(
                Flag(
                    flag_type=FlagType.CORRELATION_RISK,
                    ticker=",".join(tickers),
                    severity=Severity.WARNING,
                    description=(
                        f"Correlated positions: {', '.join(tickers)} share "
                        f"sector='{sector}' and industry='{industry}'. "
                        f"Quantitative correlation matrix is Phase 2."
                    ),
                    extra={"sector": sector, "industry": industry, "tickers": tickers},
                )
            )

    return flags


# ---------------------------------------------------------------------------
# CHECK-07: STALE
# ---------------------------------------------------------------------------


def _count_trading_days(start_date: date, end_date: date) -> int:
    """Count NYSE trading days between start_date (inclusive) and end_date (exclusive).

    Uses pandas_market_calendars for accuracy (excludes weekends and US holidays).
    """
    if start_date >= end_date:
        return 0
    try:
        cal = _get_nyse_calendar()
        import pandas as pd

        schedule = cal.schedule(
            start_date=start_date.strftime("%Y-%m-%d"),
            end_date=(end_date - pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
        )
        return len(schedule)
    except Exception:
        # Fallback: rough weekday count (ignores holidays)
        count = 0
        current = start_date
        while current < end_date:
            if current.weekday() < 5:  # Mon-Fri
                count += 1
            from datetime import timedelta

            current = current + timedelta(days=1)
        return count


def check_stale(
    *,
    ticker: str,
    entry_date_str: str,
    as_of: date | None = None,
    position_url: str = "",
) -> Flag | None:
    """Flag positions open more than 5 trading days.

    Args:
        entry_date_str: ISO 8601 date string from Paper Portfolio DB.
        as_of: Reference date (defaults to today UTC).
    """
    if not entry_date_str:
        return None

    try:
        # Parse flexible ISO date (with or without time component)
        entry_dt = datetime.fromisoformat(entry_date_str.replace("Z", "+00:00"))
        entry_d = entry_dt.date()
    except ValueError:
        logger.warning("check_stale: unparseable entry_date_str=%r for %s", entry_date_str, ticker)
        return None

    today = as_of or datetime.now(UTC).date()
    trading_days = _count_trading_days(entry_d, today)

    if trading_days > STALE_TRADING_DAYS:
        return Flag(
            flag_type=FlagType.STALE,
            ticker=ticker,
            severity=Severity.WARNING,
            description=(
                f"{ticker} has been open {trading_days} trading days "
                f"(threshold={STALE_TRADING_DAYS}, entry={entry_d})"
            ),
            extra={
                "trading_days": trading_days,
                "threshold": STALE_TRADING_DAYS,
                "entry_date": str(entry_d),
            },
            position_url=position_url,
        )
    return None


# ---------------------------------------------------------------------------
# Per-position check runner
# ---------------------------------------------------------------------------


def run_checks_for_position(
    *,
    position: dict[str, Any],
    current_price: float | None,
    as_of: date | None = None,
) -> list[Flag]:
    """Run all 6 in-scope checks for a single position.

    If current_price is None, returns a DATA_MISSING flag and skips
    price-dependent checks (STOP_PROXIMITY, TARGET_PROXIMITY, BREACH).
    STALE and concentration/correlation are computed by their callers
    (they need the full portfolio context).
    """
    ticker = position["ticker"]
    url = position.get("url", "")
    flags: list[Flag] = []

    if current_price is None:
        flags.append(
            Flag(
                flag_type=FlagType.DATA_MISSING,
                ticker=ticker,
                severity=Severity.CRITICAL,
                description=f"DATA_MISSING: STONKY-001 returned null for {ticker}",
                position_url=url,
            )
        )
        # Still run STALE check (doesn't need price)
        stale = check_stale(
            ticker=ticker,
            entry_date_str=position.get("entry_date", ""),
            as_of=as_of,
            position_url=url,
        )
        if stale:
            flags.append(stale)
        return flags

    direction = position.get("direction", "long")
    stop = position.get("stop", 0.0)
    target = position.get("target", 0.0)

    # CHECK-01
    sp = check_stop_proximity(
        ticker=ticker,
        current_price=current_price,
        stop=stop,
        direction=direction,
        position_url=url,
    )
    if sp:
        flags.append(sp)

    # CHECK-02
    tp = check_target_proximity(
        ticker=ticker,
        current_price=current_price,
        target=target,
        direction=direction,
        position_url=url,
    )
    if tp:
        flags.append(tp)

    # CHECK-03
    flags.extend(
        check_breach(
            ticker=ticker,
            current_price=current_price,
            stop=stop,
            target=target,
            direction=direction,
            position_url=url,
        )
    )

    # CHECK-07
    stale = check_stale(
        ticker=ticker,
        entry_date_str=position.get("entry_date", ""),
        as_of=as_of,
        position_url=url,
    )
    if stale:
        flags.append(stale)

    return flags
