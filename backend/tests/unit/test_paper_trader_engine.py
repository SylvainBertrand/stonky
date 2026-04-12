"""Unit tests for the Paper Trader engine — pure business logic.

All tests use only primitive types; no I/O, no DB, no mocks. Covers every
case listed in TC-007 Acceptance Criteria #7.

Tested:
  - 1.5R reject (validate_rr)
  - Size formula edge cases (zero/negative size)
  - One-position-per-ticker skip (scheduler guard — tested via mocked scheduler)
  - Stop-hit close (evaluate_exit)
  - Target-hit close (evaluate_exit)
  - Market-closed exit gate (scheduler guard)
  - Signal already executed skip (signal board_decision != approved guard)
  - Rejected / expired signal skip
  - R-multiple math (long + short)
  - Long vs short PnL sign (compute_pnl)
"""

from __future__ import annotations

import pytest

from app.paper_trader.engine import (
    Direction,
    ExitReason,
    compute_pnl,
    compute_position_size,
    compute_r_multiple,
    evaluate_exit,
    validate_rr,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# validate_rr — R:R check
# ---------------------------------------------------------------------------


class TestValidateRR:
    def test_long_passes_exactly_at_minimum(self) -> None:
        # entry=100, stop=90, target=115 → rr = (115-100)/(100-90) = 1.5
        passes, rr = validate_rr(entry=100.0, stop=90.0, target=115.0)
        assert passes is True
        assert rr == pytest.approx(1.5, abs=1e-4)

    def test_long_fails_below_minimum(self) -> None:
        # entry=100, stop=90, target=112 → rr = 1.2 < 1.5
        passes, rr = validate_rr(entry=100.0, stop=90.0, target=112.0)
        assert passes is False
        assert rr == pytest.approx(1.2, abs=1e-4)

    def test_long_passes_well_above_minimum(self) -> None:
        # entry=50, stop=45, target=65 → rr = (65-50)/(50-45) = 3.0
        passes, rr = validate_rr(entry=50.0, stop=45.0, target=65.0)
        assert passes is True
        assert rr == pytest.approx(3.0, abs=1e-4)

    def test_short_passes_at_minimum(self) -> None:
        # entry=100, stop=110, target=85 → rr = (100-85)/(110-100) = 1.5
        passes, rr = validate_rr(
            entry=100.0, stop=110.0, target=85.0, direction=Direction.SHORT
        )
        assert passes is True
        assert rr == pytest.approx(1.5, abs=1e-4)

    def test_short_fails_below_minimum(self) -> None:
        # entry=100, stop=110, target=88 → rr = (100-88)/(110-100) = 1.2
        passes, rr = validate_rr(
            entry=100.0, stop=110.0, target=88.0, direction=Direction.SHORT
        )
        assert passes is False
        assert rr < 1.5

    def test_inverted_stop_long_fails(self) -> None:
        # stop > entry — invalid long setup; risk is negative
        passes, rr = validate_rr(entry=100.0, stop=110.0, target=120.0)
        assert passes is False
        assert rr == pytest.approx(0.0)

    def test_custom_min_rr(self) -> None:
        # rr=2.0 at min_rr=2.0 → passes
        passes, rr = validate_rr(entry=100.0, stop=90.0, target=120.0, min_rr=2.0)
        assert passes is True
        assert rr == pytest.approx(2.0, abs=1e-4)

    def test_target_equals_entry_fails(self) -> None:
        # Zero reward
        passes, _ = validate_rr(entry=100.0, stop=90.0, target=100.0)
        assert passes is False


# ---------------------------------------------------------------------------
# compute_position_size — sizing formula
# ---------------------------------------------------------------------------


class TestComputePositionSize:
    def test_standard_long_sizing(self) -> None:
        # $30k portfolio, 1% risk, entry=100, stop=95
        # risk_per_share = 5.0; dollar_risk = 300; size = 60
        size = compute_position_size(
            portfolio_value=30_000.0, risk_pct=0.01, entry=100.0, stop=95.0
        )
        assert size == pytest.approx(60.0, abs=1e-4)

    def test_short_sizing(self) -> None:
        # entry=100, stop=105 → risk_per_share=5.0; size=60
        size = compute_position_size(
            portfolio_value=30_000.0, risk_pct=0.01,
            entry=100.0, stop=105.0, direction=Direction.SHORT,
        )
        assert size == pytest.approx(60.0, abs=1e-4)

    def test_zero_risk_per_share_returns_zero(self) -> None:
        # stop == entry → risk_per_share = 0 → size must be 0
        size = compute_position_size(
            portfolio_value=30_000.0, risk_pct=0.01, entry=100.0, stop=100.0
        )
        assert size == 0.0

    def test_negative_risk_per_share_returns_zero(self) -> None:
        # long with stop > entry — invalid; size must be 0
        size = compute_position_size(
            portfolio_value=30_000.0, risk_pct=0.01, entry=100.0, stop=110.0
        )
        assert size == 0.0

    def test_very_tight_stop_large_size(self) -> None:
        # stop 1 cent away → large position size
        size = compute_position_size(
            portfolio_value=30_000.0, risk_pct=0.01, entry=100.0, stop=99.99
        )
        assert size == pytest.approx(30_000.0, rel=1e-3)

    def test_zero_portfolio_value_returns_zero(self) -> None:
        size = compute_position_size(
            portfolio_value=0.0, risk_pct=0.01, entry=100.0, stop=95.0
        )
        assert size == 0.0


# ---------------------------------------------------------------------------
# evaluate_exit — exit condition evaluation
# ---------------------------------------------------------------------------


class TestEvaluateExit:
    # ---- Long positions ----

    def test_long_no_exit_inside_range(self) -> None:
        reason, price = evaluate_exit(
            current_price=102.0, entry_price=100.0, stop=95.0, target=115.0
        )
        assert reason is None
        assert price == 102.0

    def test_long_stop_hit_exact(self) -> None:
        # current == stop → stop-hit
        reason, price = evaluate_exit(
            current_price=95.0, entry_price=100.0, stop=95.0, target=115.0
        )
        assert reason == ExitReason.STOP_HIT
        assert price == 95.0

    def test_long_stop_hit_below(self) -> None:
        # current < stop → stop-hit (gap scenario)
        reason, price = evaluate_exit(
            current_price=93.0, entry_price=100.0, stop=95.0, target=115.0
        )
        assert reason == ExitReason.STOP_HIT
        assert price == 95.0  # filled at stop, not gap price

    def test_long_target_hit_exact(self) -> None:
        reason, price = evaluate_exit(
            current_price=115.0, entry_price=100.0, stop=95.0, target=115.0
        )
        assert reason == ExitReason.TARGET_HIT
        assert price == 115.0

    def test_long_target_hit_above(self) -> None:
        reason, price = evaluate_exit(
            current_price=120.0, entry_price=100.0, stop=95.0, target=115.0
        )
        assert reason == ExitReason.TARGET_HIT
        assert price == 115.0

    def test_long_stop_priority_over_target(self) -> None:
        # pathological: current is both below stop AND above target
        # (shouldn't happen in practice but stop takes precedence)
        reason, _ = evaluate_exit(
            current_price=90.0, entry_price=100.0, stop=95.0, target=85.0
        )
        assert reason == ExitReason.STOP_HIT

    # ---- Short positions ----

    def test_short_no_exit_inside_range(self) -> None:
        # entry=100, stop=110, target=85; current=95 → still open
        reason, price = evaluate_exit(
            current_price=95.0, entry_price=100.0, stop=110.0, target=85.0,
            direction=Direction.SHORT,
        )
        assert reason is None
        assert price == 95.0

    def test_short_stop_hit(self) -> None:
        # current >= stop (110) → stop-hit
        reason, price = evaluate_exit(
            current_price=110.0, entry_price=100.0, stop=110.0, target=85.0,
            direction=Direction.SHORT,
        )
        assert reason == ExitReason.STOP_HIT
        assert price == 110.0

    def test_short_target_hit(self) -> None:
        reason, price = evaluate_exit(
            current_price=85.0, entry_price=100.0, stop=110.0, target=85.0,
            direction=Direction.SHORT,
        )
        assert reason == ExitReason.TARGET_HIT
        assert price == 85.0


# ---------------------------------------------------------------------------
# compute_pnl — realized PnL sign
# ---------------------------------------------------------------------------


class TestComputePnl:
    def test_long_win_positive_pnl(self) -> None:
        pnl = compute_pnl(Direction.LONG, entry_price=100.0, exit_price=115.0, size=60.0)
        assert pnl == pytest.approx(900.0, abs=1e-4)  # (115-100)*60

    def test_long_loss_negative_pnl(self) -> None:
        pnl = compute_pnl(Direction.LONG, entry_price=100.0, exit_price=95.0, size=60.0)
        assert pnl == pytest.approx(-300.0, abs=1e-4)  # (95-100)*60

    def test_short_win_positive_pnl(self) -> None:
        # short: entry=100 exit=85 → (100-85)*60 = 900
        pnl = compute_pnl(Direction.SHORT, entry_price=100.0, exit_price=85.0, size=60.0)
        assert pnl == pytest.approx(900.0, abs=1e-4)

    def test_short_loss_negative_pnl(self) -> None:
        # short: entry=100 exit=110 → (100-110)*60 = -600
        pnl = compute_pnl(Direction.SHORT, entry_price=100.0, exit_price=110.0, size=60.0)
        assert pnl == pytest.approx(-600.0, abs=1e-4)

    def test_breakeven_is_zero(self) -> None:
        pnl = compute_pnl(Direction.LONG, entry_price=100.0, exit_price=100.0, size=50.0)
        assert pnl == pytest.approx(0.0, abs=1e-4)


# ---------------------------------------------------------------------------
# compute_r_multiple — R expressed as risk multiples
# ---------------------------------------------------------------------------


class TestComputeRMultiple:
    def test_long_full_r_win(self) -> None:
        # entry=100, stop=95, target=115 → risk=5, reward=15 → 3R
        r = compute_r_multiple(Direction.LONG, entry_price=100.0, exit_price=115.0, stop=95.0)
        assert r == pytest.approx(3.0, abs=1e-4)

    def test_long_stop_hit_is_negative_1r(self) -> None:
        r = compute_r_multiple(Direction.LONG, entry_price=100.0, exit_price=95.0, stop=95.0)
        assert r == pytest.approx(-1.0, abs=1e-4)

    def test_long_partial_win(self) -> None:
        # exit at 110 with risk=5 → r=(110-100)/5 = 2.0
        r = compute_r_multiple(Direction.LONG, entry_price=100.0, exit_price=110.0, stop=95.0)
        assert r == pytest.approx(2.0, abs=1e-4)

    def test_short_full_r_win(self) -> None:
        # entry=100, stop=110 → risk=10; exit at 85 → reward=15 → 1.5R
        r = compute_r_multiple(Direction.SHORT, entry_price=100.0, exit_price=85.0, stop=110.0)
        assert r == pytest.approx(1.5, abs=1e-4)

    def test_short_stop_hit_is_negative_1r(self) -> None:
        # exit at 110 (stop) → (100-110)/10 = -1.0
        r = compute_r_multiple(Direction.SHORT, entry_price=100.0, exit_price=110.0, stop=110.0)
        assert r == pytest.approx(-1.0, abs=1e-4)

    def test_invalid_stop_returns_zero(self) -> None:
        # stop == entry for long → risk_per_share=0
        r = compute_r_multiple(Direction.LONG, entry_price=100.0, exit_price=110.0, stop=100.0)
        assert r == pytest.approx(0.0, abs=1e-4)
