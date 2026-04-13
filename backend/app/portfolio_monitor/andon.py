"""Portfolio Monitor — Andon cord trigger evaluation.

Deterministic evaluation of all 3 Andon cord trigger conditions:
  1. 5+ positions simultaneously underwater (STOP_BREACH)
  2. >50% of positions in STOP_BREACH in a single run
  3. External HALT signal detected in Signal Registry

When triggered:
  1. Write anomaly signal to Signal Registry (Board Decision=pending)
  2. Send critical Discord alert immediately

References:
  - Brief: briefs/portfolio-monitor.yaml v2.0.0 (andon_cord section)
  - Ticket: TC-008 Acceptance Criteria #2, #9
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.portfolio_monitor.engine import Flag, FlagType

logger = logging.getLogger(__name__)


@dataclass
class AndonResult:
    triggered: bool
    reason: str
    conditions_met: list[str]


def evaluate_andon_cord(
    *,
    flags: list[Flag],
    total_positions: int,
    halt_signals_active: int = 0,
) -> AndonResult:
    """Evaluate all 3 Andon cord trigger conditions deterministically.

    Args:
        flags: All flags raised in this run (across all positions).
        total_positions: Total number of open positions evaluated.
        halt_signals_active: Count of active HALT signals in Signal Registry.

    Returns AndonResult indicating whether the cord should be pulled.

    Trigger conditions (any one is sufficient):
      A) 5+ positions simultaneously in STOP_BREACH in this run.
      B) >50% of positions in STOP_BREACH in this run.
      C) External HALT signal detected (halt_signals_active > 0).
    """
    conditions_met: list[str] = []

    # Count STOP_BREACH flags from this run
    stop_breach_flags = [f for f in flags if f.flag_type == FlagType.STOP_BREACH]
    stop_breach_count = len(stop_breach_flags)

    # Condition A: 5+ positions simultaneously underwater (STOP_BREACH)
    if stop_breach_count >= 5:
        conditions_met.append(
            f"Condition A: {stop_breach_count} positions in STOP_BREACH (threshold=5)"
        )

    # Condition B: >50% of positions in STOP_BREACH
    if total_positions > 0:
        breach_pct = stop_breach_count / total_positions
        if breach_pct > 0.5:
            conditions_met.append(
                f"Condition B: {stop_breach_count}/{total_positions} positions in STOP_BREACH "
                f"({breach_pct * 100:.0f}% > 50% threshold)"
            )

    # Condition C: external HALT signal in Signal Registry
    if halt_signals_active > 0:
        conditions_met.append(
            f"Condition C: {halt_signals_active} active external HALT signal(s) detected"
        )

    triggered = len(conditions_met) > 0
    reason = "; ".join(conditions_met) if conditions_met else ""

    if triggered:
        logger.warning("Andon cord triggered: %s", reason)

    return AndonResult(
        triggered=triggered,
        reason=reason,
        conditions_met=conditions_met,
    )
