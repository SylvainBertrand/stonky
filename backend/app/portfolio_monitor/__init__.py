"""Portfolio Monitor Stonky service.

Deterministic 15-min monitor for all open paper-trading positions.
Runs 6 of 7 checks defined in briefs/portfolio-monitor.yaml v2.0.0:

  CHECK-01  STOP_PROXIMITY      — within 2% of stop level
  CHECK-02  TARGET_PROXIMITY    — within 2% of target level
  CHECK-03  STOP_BREACH/TARGET_BREACH — level crossed (immediate alert)
  CHECK-04  CONCENTRATION_RISK  — single position >10% or sector >30%
  CHECK-05  CORRELATION_RISK    — same sector+industry pair heuristic
  CHECK-07  STALE               — open >5 trading days

Check 6 (THESIS_DRIFT) is OUT OF SCOPE (qualitative, moved to weekly
research-mode Claude Code run per Option A, AC #3).

References:
  - Brief: briefs/portfolio-monitor.yaml v2.0.0
  - Ticket: TC-008
"""
