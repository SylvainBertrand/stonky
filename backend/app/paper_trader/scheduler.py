"""Paper Trader scheduler job and run orchestration.

The public entry point is ``run_paper_trader()``. It is called both by the
APScheduler cron job (every 15 min during NYSE hours Mon–Fri) and by the
manual API trigger (POST /api/paper-trader/run).

Execution flow per run (mirrors brief v1.0.0):
  1. Market-hours gate — if NYSE is not in regular session, skip all
     position actions (informational-only sweep) and send summary.
  2. Sweep open positions — fetch current prices, evaluate exits, close hits.
  3. Process approved signals — validate R:R, compute sizing, open positions.
  4. Write Execution Log (mandatory, every run).
  5. Send Discord run-summary (mandatory, every run — silent runs = failures).

References:
  - Brief: briefs/paper-trader.yaml v1.0.0
  - Ticket: TC-007 Acceptance Criteria #2, #4, #6, #7
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from app.agents_common.scheduler import is_regular_session
from app.config import settings
from app.paper_trader import discord as disc
from app.paper_trader import notion_client as nc
from app.paper_trader.engine import (
    Direction,
    cap_position_size,
    compute_pnl,
    compute_position_size,
    compute_r_multiple,
    evaluate_exit,
    validate_rr,
)
from app.paper_trader.schemas import RunResult
from app.services.price_service import TickerNotFoundError, get_current_price

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main run function
# ---------------------------------------------------------------------------


async def run_paper_trader() -> RunResult:
    """Execute one full paper-trader cycle and return a run summary.

    This function is the single authoritative code path for both the scheduler
    job and the manual API trigger.  It is idempotent within a single run —
    calling it twice will not double-open positions because the portfolio query
    enforces one-position-per-ticker.
    """
    run_id = f"paper-trader-{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')}"
    logger.info("paper_trader run start: %s", run_id)

    errors: list[str] = []
    opened = 0
    closed = 0
    skipped = 0
    last_notion_url = ""
    status = "success"

    # ------------------------------------------------------------------
    # 1. Market-hours gate
    # ------------------------------------------------------------------
    market_open = is_regular_session()

    if not market_open:
        logger.info(
            "paper_trader: market not in regular session — skipping position actions",
        )

    try:
        # ------------------------------------------------------------------
        # 2. Sweep open positions for exits (only when market is open)
        # ------------------------------------------------------------------
        if market_open:
            closed, last_notion_url, close_errors = await _sweep_exits(run_id)
            errors.extend(close_errors)

        # ------------------------------------------------------------------
        # 3. Process approved signals (only when market is open)
        # ------------------------------------------------------------------
        if market_open:
            opened, open_url, open_errors, skipped = await _process_signals(run_id)
            errors.extend(open_errors)
            if open_url:
                last_notion_url = open_url

        # ------------------------------------------------------------------
        # 4. Determine run status
        # ------------------------------------------------------------------
        if errors:
            status = "partial" if (opened > 0 or closed > 0) else "failed"

    except Exception as exc:
        logger.error("paper_trader run failed unexpectedly: %s", exc, exc_info=True)
        errors.append(str(exc))
        status = "failed"

    # ------------------------------------------------------------------
    # 5. Write Execution Log (mandatory — every run)
    # ------------------------------------------------------------------
    try:
        await nc.write_execution_log(
            run_id=run_id,
            status=status,
            errors=errors or None,
            output_page_url=last_notion_url,
        )
    except Exception as exc:
        logger.error("paper_trader: failed to write execution log: %s", exc)
        errors.append(f"execution_log_write_failed: {exc}")

    # ------------------------------------------------------------------
    # 6. Send Discord run summary (mandatory — every run)
    # ------------------------------------------------------------------
    try:
        await disc.send_run_summary(
            run_id=run_id,
            positions_opened=opened,
            positions_closed=closed,
            status=status,
            notion_url=last_notion_url,
        )
    except Exception as exc:
        logger.error("paper_trader: failed to send Discord summary: %s", exc)
        errors.append(f"discord_summary_failed: {exc}")

    result = RunResult(
        run_id=run_id,
        status=status,
        market_open=market_open,
        positions_opened=opened,
        positions_closed=closed,
        signals_skipped=skipped,
        errors=errors,
    )
    logger.info(
        "paper_trader run complete: %s status=%s opened=%d closed=%d skipped=%d",
        run_id,
        status,
        opened,
        closed,
        skipped,
    )
    return result


# ---------------------------------------------------------------------------
# Exit sweep helper
# ---------------------------------------------------------------------------


async def _sweep_exits(run_id: str) -> tuple[int, str, list[str]]:
    """Fetch open positions and close any that have hit stop or target.

    Reads portfolio state, credits cash on each close, and updates the
    portfolio-state row in Notion.

    Returns (closed_count, last_notion_url, errors).
    """
    closed = 0
    last_url = ""
    errors: list[str] = []

    try:
        portfolio_state = await nc.get_portfolio_state()
    except Exception as exc:
        logger.warning("_sweep_exits: portfolio state unavailable: %s", exc)
        portfolio_state = None

    cash_balance = portfolio_state["cash_balance"] if portfolio_state else 0.0
    equity = portfolio_state["equity"] if portfolio_state else 0.0
    reserved_short_collateral = (
        portfolio_state.get("reserved_short_collateral", 0.0) if portfolio_state else 0.0
    )

    try:
        positions = await nc.get_open_positions()
    except Exception as exc:
        errors.append(f"get_open_positions failed: {exc}")
        return 0, "", errors

    for pos in positions:
        ticker = pos["ticker"]
        direction = Direction(pos.get("direction", "long"))
        entry_price = pos["entry_price"]
        stop = pos["stop"]
        target = pos["target"]
        size = pos["size"]
        position_id = pos["id"]
        signal_id = pos.get("signal_id", "")
        portfolio_url = pos["url"]

        # Fetch live price
        try:
            quote = await get_current_price(ticker)
            current_price = quote.price
        except TickerNotFoundError:
            errors.append(f"price_not_found: {ticker}")
            continue
        except Exception as exc:
            errors.append(f"price_fetch_error: {ticker}: {exc}")
            continue

        exit_reason, exit_price = evaluate_exit(
            current_price=current_price,
            entry_price=entry_price,
            stop=stop,
            target=target,
            direction=direction,
        )

        if exit_reason is None:
            continue

        # Compute financials
        realized_pnl = compute_pnl(direction, entry_price, exit_price, size)
        r_multiple = compute_r_multiple(direction, entry_price, exit_price, stop)

        # Write to Notion
        try:
            await nc.close_portfolio_position(
                position_id=position_id,
                exit_price=exit_price,
                exit_reason=exit_reason.value,
                realized_pnl=realized_pnl,
                r_multiple=r_multiple,
            )
            journal_entry = await nc.create_trade_journal_close(
                ticker=ticker,
                signal_id=signal_id,
                exit_price=exit_price,
                exit_reason=exit_reason.value,
                realized_pnl=realized_pnl,
                r_multiple=r_multiple,
                portfolio_page_url=portfolio_url,
            )
            last_url = journal_entry["url"]
        except Exception as exc:
            errors.append(f"close_position_error: {ticker}: {exc}")
            continue

        # Update portfolio state — credit cash from close proceeds
        if portfolio_state:
            if direction == Direction.LONG:
                cash_balance += size * exit_price
            else:
                # Short close: release collateral, credit/debit by realized P&L
                collateral_amount = size * entry_price
                reserved_short_collateral -= collateral_amount
                cash_balance += collateral_amount + realized_pnl
            # Equity tracks cash + collateral (open long market value not tracked)
            equity += realized_pnl
            try:
                await nc.update_portfolio_state(
                    page_id=portfolio_state["page_id"],
                    cash_balance=round(cash_balance, 2),
                    equity=round(equity, 2),
                    reserved_short_collateral=round(reserved_short_collateral, 2),
                )
            except Exception as exc:
                errors.append(f"portfolio_state_update_error: {ticker}: {exc}")

        # Discord notification
        try:
            await disc.send_position_close(
                ticker=ticker,
                exit_price=exit_price,
                exit_reason=exit_reason.value,
                realized_pnl=realized_pnl,
                r_multiple=r_multiple,
                notion_url=last_url,
            )
        except Exception as exc:
            logger.warning("discord position_close failed for %s: %s", ticker, exc)

        closed += 1
        logger.info(
            "_sweep_exits: closed %s exit_reason=%s r=%.2f pnl=%.2f",
            ticker,
            exit_reason.value,
            r_multiple,
            realized_pnl,
        )

    return closed, last_url, errors


# ---------------------------------------------------------------------------
# Signal processing helper
# ---------------------------------------------------------------------------


async def _process_signals(run_id: str) -> tuple[int, str, list[str], int]:
    """Process approved signals and open new positions.

    Reads portfolio state for cash-constrained sizing (TC-SWE-110).
    Processes signals sequentially — each signal sees the cash_balance
    left by prior signals in the same run.

    Returns (opened_count, last_notion_url, errors, skipped_count).
    """
    opened = 0
    skipped = 0
    last_url = ""
    errors: list[str] = []

    try:
        signals = await nc.get_approved_signals()
    except Exception as exc:
        errors.append(f"get_approved_signals failed: {exc}")
        return 0, "", errors, 0

    # Build set of tickers already open (one-position-per-ticker rule)
    try:
        open_positions = await nc.get_open_positions()
    except Exception as exc:
        errors.append(f"get_open_positions failed during signal processing: {exc}")
        return 0, "", errors, 0

    open_tickers = {p["ticker"].upper() for p in open_positions}
    # TC-SWE-110: signal_id idempotency guard
    open_signal_ids = {p.get("signal_id", "") for p in open_positions} - {""}

    # TC-SWE-110: read portfolio state for cash-constrained sizing
    try:
        portfolio_state = await nc.get_portfolio_state()
    except Exception as exc:
        errors.append(f"get_portfolio_state failed: {exc}")
        # Fall back to config if portfolio state unavailable
        portfolio_state = None

    if portfolio_state:
        cash_balance = portfolio_state["cash_balance"]
        equity = portfolio_state["equity"]
        reserved_short_collateral = portfolio_state.get("reserved_short_collateral", 0.0)
    else:
        cash_balance = settings.paper_trader_portfolio_value
        equity = settings.paper_trader_portfolio_value
        reserved_short_collateral = 0.0

    for signal in signals:
        ticker = signal["ticker"].upper()
        signal_id = signal["id"]
        direction = Direction(signal.get("direction", "long"))
        stop = signal["stop"]
        target = signal["target"]
        thesis_id = signal.get("thesis_id", "")

        # TC-SWE-116: short signals require portfolio_state for collateral tracking
        if direction == Direction.SHORT and portfolio_state is None:
            logger.info(
                "_process_signals: skipping short %s — portfolio state unavailable, "
                "cannot track collateral",
                ticker,
            )
            skipped += 1
            continue

        # Skip if already have an open position in this ticker (AC #4)
        if ticker in open_tickers:
            logger.info("_process_signals: skipping %s — already has open position", ticker)
            skipped += 1
            continue

        # TC-SWE-110: signal_id idempotency — never open same signal twice
        if signal_id in open_signal_ids:
            logger.info(
                "_process_signals: skipping %s — signal %s already has open position",
                ticker,
                signal_id,
            )
            skipped += 1
            continue

        # Fetch live execution price (never use thesis entry price — AC #4)
        try:
            quote = await get_current_price(ticker)
            entry_price = quote.price
        except TickerNotFoundError:
            errors.append(f"price_not_found: {ticker}")
            skipped += 1
            continue
        except Exception as exc:
            errors.append(f"price_fetch_error: {ticker}: {exc}")
            skipped += 1
            continue

        # R:R validation (AC #4)
        passes_rr, rr_ratio = validate_rr(
            entry=entry_price,
            stop=stop,
            target=target,
            direction=direction,
            min_rr=settings.paper_trader_min_rr,
        )
        if not passes_rr:
            logger.info(
                "_process_signals: skipping %s — R:R %.2f below minimum %.2f",
                ticker,
                rr_ratio,
                settings.paper_trader_min_rr,
            )
            skipped += 1
            continue

        # Position sizing — risk-based then cash-capped (TC-SWE-110)
        risk_based_size = compute_position_size(
            portfolio_value=equity,
            risk_pct=settings.paper_trader_risk_pct,
            entry=entry_price,
            stop=stop,
            direction=direction,
        )
        if risk_based_size <= 0:
            logger.warning(
                "_process_signals: skipping %s — computed risk_based_size=%.4f",
                ticker,
                risk_based_size,
            )
            skipped += 1
            continue

        # TC-SWE-110: cap by available cash (no leverage for longs)
        size = cap_position_size(
            risk_based_size=risk_based_size,
            cash_balance=cash_balance,
            entry_price=entry_price,
        )
        if size < 1:
            logger.info(
                "_process_signals: skipping %s — insufficient cash (%.2f) for entry @ %.2f",
                ticker,
                cash_balance,
                entry_price,
            )
            skipped += 1
            continue

        risk_amount = equity * settings.paper_trader_risk_pct

        # Write to Notion
        try:
            portfolio_entry = await nc.create_portfolio_position(
                ticker=ticker,
                entry_price=entry_price,
                stop=stop,
                target=target,
                size=size,
                direction=direction.value,
                signal_id=signal_id,
                thesis_id=thesis_id,
                risk_amount=risk_amount,
                rr_ratio=rr_ratio,
            )
            journal_entry = await nc.create_trade_journal_open(
                ticker=ticker,
                signal_id=signal_id,
                entry_price=entry_price,
                stop=stop,
                target=target,
                size=size,
                risk_amount=risk_amount,
                rr_ratio=rr_ratio,
                direction=direction.value,
                portfolio_page_url=portfolio_entry["url"],
            )
            await nc.mark_signal_executed(signal_id)
            last_url = journal_entry["url"]
        except Exception as exc:
            errors.append(f"open_position_error: {ticker}: {exc}")
            continue

        # TC-SWE-110/116: debit cash and update portfolio state
        notional = size * entry_price
        cash_balance -= notional
        if direction == Direction.SHORT:
            reserved_short_collateral += notional
        if portfolio_state:
            try:
                await nc.update_portfolio_state(
                    page_id=portfolio_state["page_id"],
                    cash_balance=round(cash_balance, 2),
                    equity=round(equity, 2),
                    reserved_short_collateral=round(reserved_short_collateral, 2),
                )
            except Exception as exc:
                errors.append(f"portfolio_state_update_error: {ticker}: {exc}")

        # Discord notification
        try:
            await disc.send_position_open(
                ticker=ticker,
                entry_price=entry_price,
                stop=stop,
                target=target,
                risk_amount=risk_amount,
                rr_ratio=rr_ratio,
                notion_url=portfolio_entry["url"],
                direction=direction.value,
            )
        except Exception as exc:
            logger.warning("discord position_open failed for %s: %s", ticker, exc)

        open_tickers.add(ticker)
        open_signal_ids.add(signal_id)
        opened += 1
        logger.info(
            "_process_signals: opened %s @ %.4f size=%d rr=%.2f cash_remaining=%.2f",
            ticker,
            entry_price,
            size,
            rr_ratio,
            cash_balance,
        )

    return opened, last_url, errors, skipped
