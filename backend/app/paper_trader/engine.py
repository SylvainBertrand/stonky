"""Paper Trader engine — pure business-logic functions.

All functions are stateless and side-effect-free; they accept only primitive
types so they are trivially unit-testable without mocks or DB fixtures.

References:
  - Brief: briefs/paper-trader.yaml v1.0.0
  - Ticket: TC-007 Acceptance Criteria #1
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class Direction(str, Enum):
    LONG = "long"
    SHORT = "short"


class ExitReason(str, Enum):
    STOP_HIT = "stop-hit"
    TARGET_HIT = "target-hit"


# ---------------------------------------------------------------------------
# Core engine functions
# ---------------------------------------------------------------------------


def validate_rr(
    entry: float,
    stop: float,
    target: float,
    direction: Direction = Direction.LONG,
    min_rr: float = 1.5,
) -> tuple[bool, float]:
    """Check whether the reward-to-risk ratio meets the minimum threshold.

    Returns (passes, rr_ratio). For long positions:
        rr = (target - entry) / (entry - stop)
    For short positions:
        rr = (entry - target) / (stop - entry)

    A position fails validation when rr < min_rr or when the denominator is
    zero or negative (invalid setup).
    """
    if direction == Direction.LONG:
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target

    if risk <= 0:
        return False, 0.0

    rr = reward / risk
    return rr >= min_rr, round(rr, 4)


def compute_position_size(
    portfolio_value: float,
    risk_pct: float,
    entry: float,
    stop: float,
    direction: Direction = Direction.LONG,
) -> float:
    """Compute the number of shares/units using the fixed-risk model.

    size = (portfolio_value × risk_pct) / |entry - stop|

    Returns 0.0 when the result is zero or negative (invalid setup); callers
    must skip the trade and log a warning in that case (brief guardrail).
    """
    if direction == Direction.LONG:
        risk_per_share = entry - stop
    else:
        risk_per_share = stop - entry

    if risk_per_share <= 0:
        return 0.0

    dollar_risk = portfolio_value * risk_pct
    size = dollar_risk / risk_per_share
    return max(0.0, size)


def evaluate_exit(
    current_price: float,
    entry_price: float,
    stop: float,
    target: float,
    direction: Direction = Direction.LONG,
) -> tuple[ExitReason | None, float]:
    """Determine whether a position should be closed at the current price.

    Returns (exit_reason, exit_price) when an exit condition is met, or
    (None, current_price) when the position should remain open.

    Priority: stop checked before target (preserves capital first).
    """
    if direction == Direction.LONG:
        if current_price <= stop:
            return ExitReason.STOP_HIT, stop
        if current_price >= target:
            return ExitReason.TARGET_HIT, target
    else:
        if current_price >= stop:
            return ExitReason.STOP_HIT, stop
        if current_price <= target:
            return ExitReason.TARGET_HIT, target

    return None, current_price


def compute_pnl(
    direction: Direction,
    entry_price: float,
    exit_price: float,
    size: float,
) -> float:
    """Compute the realized PnL in dollars for a closed position.

    Long:  (exit - entry) * size
    Short: (entry - exit) * size
    """
    if direction == Direction.LONG:
        return round((exit_price - entry_price) * size, 4)
    return round((entry_price - exit_price) * size, 4)


def compute_r_multiple(
    direction: Direction,
    entry_price: float,
    exit_price: float,
    stop: float,
) -> float:
    """Express the realized gain/loss as a multiple of initial risk (R).

    Positive R = win (exit beyond target direction), negative R = loss.

    Long:  (exit - entry) / (entry - stop)
    Short: (entry - exit) / (stop - entry)
    """
    if direction == Direction.LONG:
        risk_per_share = entry_price - stop
    else:
        risk_per_share = stop - entry_price

    if risk_per_share <= 0:
        return 0.0

    if direction == Direction.LONG:
        return round((exit_price - entry_price) / risk_per_share, 4)
    return round((entry_price - exit_price) / risk_per_share, 4)


# ---------------------------------------------------------------------------
# Convenience dataclass used by the scheduler
# ---------------------------------------------------------------------------


@dataclass
class PositionResult:
    """Summary of a single position open or close action in one engine run."""

    action: str  # "opened" | "closed" | "skipped"
    ticker: str
    reason: str  # human-readable, e.g. "stop-hit", "rr_below_minimum"
    entry_price: float = 0.0
    exit_price: float = 0.0
    size: float = 0.0
    pnl: float = 0.0
    r_multiple: float = 0.0
    notion_url: str = ""
