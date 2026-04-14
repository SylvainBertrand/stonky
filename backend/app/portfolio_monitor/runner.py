"""Portfolio Monitor runner — orchestrates a single end-to-end run.

Execution flow per run (mirrors brief v2.0.0):
  1. Market-hours gate — if NYSE not in regular session, skip (return early).
  2. Read open positions from Paper Portfolio DB.
  3. Fetch live prices for all tickers via STONKY-001 (get_current_price).
  4. Run all 6 in-scope checks on every position:
       CHECK-01 STOP_PROXIMITY, CHECK-02 TARGET_PROXIMITY,
       CHECK-03 STOP_BREACH/TARGET_BREACH, CHECK-07 STALE
  5. Run portfolio-level checks:
       CHECK-04 CONCENTRATION_RISK, CHECK-05 CORRELATION_RISK
  6. Send immediate critical Discord for each STOP_BREACH / TARGET_BREACH.
  7. Evaluate Andon cord triggers.
  8. If Andon triggered: write Signal Registry anomaly + send critical Discord.
  9. Create Notion report page (every run, even when zero flags).
  10. Send per-run Discord summary (every run).
  11. Write Execution Log row (every run).

Check 6 (THESIS_DRIFT) is OUT OF SCOPE — moved to weekly research mode.
DATA_MISSING is a critical flag, never a silent skip.
Never closes positions — Portfolio Monitor flags only.

References:
  - Brief: briefs/portfolio-monitor.yaml v2.0.0
  - Ticket: TC-008 Acceptance Criteria #2, #4, #5, #6
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.agents_common import notion_client as nc
from app.agents_common.discord import send_critical_alert
from app.agents_common.scheduler import is_regular_session
from app.portfolio_monitor.andon import AndonResult, evaluate_andon_cord
from app.portfolio_monitor.engine import (
    Flag,
    FlagType,
    Severity,
    check_concentration_risk,
    check_correlation_risk,
    run_checks_for_position,
)
from app.portfolio_monitor.report import create_run_report, send_run_summary
from app.services.price_service import TickerNotFoundError, get_current_price

logger = logging.getLogger(__name__)


@dataclass
class RunSummary:
    """Summary returned by a single portfolio-monitor run."""

    run_id: str
    status: str
    market_open: bool
    positions_evaluated: int
    flags_raised: list[str] = field(default_factory=list)
    flag_types: list[str] = field(default_factory=list)
    critical_flags: list[str] = field(default_factory=list)
    andon_triggered: bool = False
    andon_reason: str = ""
    report_url: str = ""
    errors: list[str] = field(default_factory=list)


async def run_portfolio_monitor() -> RunSummary:
    """Execute one full portfolio-monitor cycle and return a run summary.

    Called both by the 15-min APScheduler job and the manual API trigger.
    """
    now_utc = datetime.now(UTC)
    run_id = f"portfolio-monitor-{now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}"
    logger.info("portfolio_monitor run start: %s", run_id)

    errors: list[str] = []
    all_flags: list[Flag] = []
    positions_evaluated = 0
    report_url = ""
    status = "success"
    andon_result = AndonResult(triggered=False, reason="", conditions_met=[])

    # ------------------------------------------------------------------
    # 1. Market-hours gate
    # ------------------------------------------------------------------
    market_open = is_regular_session()

    if not market_open:
        logger.info(
            "portfolio_monitor: market not in regular session — skipping run",
        )
        # Write execution log even for skipped runs (brief: ALWAYS write)
        await _write_log(run_id=run_id, status="success", errors=[], report_url="")
        return RunSummary(
            run_id=run_id,
            status="success",
            market_open=False,
            positions_evaluated=0,
        )

    try:
        # ------------------------------------------------------------------
        # 2. Read open positions
        # ------------------------------------------------------------------
        try:
            positions = await nc.get_open_positions()
        except Exception as exc:
            errors.append(f"get_open_positions failed: {exc}")
            status = "failed"
            positions = []

        positions_evaluated = len(positions)

        # ------------------------------------------------------------------
        # 3. Fetch live prices (STONKY-001)
        # ------------------------------------------------------------------
        prices: dict[str, float | None] = {}
        for pos in positions:
            ticker = pos["ticker"]
            try:
                quote = await get_current_price(ticker)
                prices[ticker] = quote.price
            except TickerNotFoundError:
                prices[ticker] = None
                errors.append(f"price_not_found: {ticker}")
            except Exception as exc:
                prices[ticker] = None
                errors.append(f"price_fetch_error: {ticker}: {exc}")

        # ------------------------------------------------------------------
        # 4. Per-position checks (CHECK-01, -02, -03, -07)
        # ------------------------------------------------------------------
        for pos in positions:
            ticker = pos["ticker"]
            current_price = prices.get(ticker)
            pos_flags = run_checks_for_position(
                position=pos,
                current_price=current_price,
                as_of=now_utc.date(),
            )
            all_flags.extend(pos_flags)

        # ------------------------------------------------------------------
        # 5. Portfolio-level checks (CHECK-04, -05)
        # ------------------------------------------------------------------
        # Build prices dict with only non-None values for concentration check
        prices_known: dict[str, float] = {t: p for t, p in prices.items() if p is not None}
        all_flags.extend(check_concentration_risk(positions, prices_known))
        all_flags.extend(check_correlation_risk(positions))

        # ------------------------------------------------------------------
        # 6. Immediate critical Discord for STOP_BREACH / TARGET_BREACH
        # ------------------------------------------------------------------
        for flag in all_flags:
            if flag.flag_type in (FlagType.STOP_BREACH, FlagType.TARGET_BREACH):
                try:
                    price = prices.get(flag.ticker) or 0.0
                    await send_critical_alert(
                        flag_type=flag.flag_type.value,
                        ticker=flag.ticker,
                        current_price=price,
                        description=flag.description,
                        report_url="",  # report not created yet; will update below
                    )
                except Exception as exc:
                    logger.warning(
                        "portfolio_monitor: critical alert failed for %s: %s", flag.ticker, exc
                    )

        # ------------------------------------------------------------------
        # 7. Andon cord evaluation
        # ------------------------------------------------------------------
        try:
            halt_signals = await nc.get_active_halt_signals()
            halt_count = len(halt_signals)
        except Exception as exc:
            errors.append(f"get_active_halt_signals failed: {exc}")
            halt_count = 0

        andon_result = evaluate_andon_cord(
            flags=all_flags,
            total_positions=positions_evaluated,
            halt_signals_active=halt_count,
        )

        # ------------------------------------------------------------------
        # 8. Andon cord action: write Signal Registry + critical Discord
        # ------------------------------------------------------------------
        if andon_result.triggered:
            try:
                anomaly_page = await nc.write_signal_anomaly(description=andon_result.reason)
                await send_critical_alert(
                    flag_type="ANDON_CORD",
                    ticker="PORTFOLIO",
                    current_price=0.0,
                    description=andon_result.reason,
                    report_url=anomaly_page.get("url", ""),
                )
            except Exception as exc:
                errors.append(f"andon_action_failed: {exc}")
                logger.error("portfolio_monitor: Andon cord action failed: %s", exc)

        # ------------------------------------------------------------------
        # Determine status based on errors and DATA_MISSING flags
        # ------------------------------------------------------------------
        data_missing_count = sum(1 for f in all_flags if f.flag_type == FlagType.DATA_MISSING)
        if data_missing_count > 0:
            errors.append(f"DATA_MISSING for {data_missing_count} position(s)")
        if errors and status != "failed":
            status = "partial" if positions_evaluated > 0 else "failed"

    except Exception as exc:
        logger.error("portfolio_monitor run failed unexpectedly: %s", exc, exc_info=True)
        errors.append(str(exc))
        status = "failed"

    # ------------------------------------------------------------------
    # 9. Create Notion report page (every run, even zero flags)
    # ------------------------------------------------------------------
    try:
        report_url = await create_run_report(
            run_id=run_id,
            run_timestamp=now_utc,
            positions_evaluated=positions_evaluated,
            flags=all_flags,
            andon_triggered=andon_result.triggered,
            andon_reason=andon_result.reason,
            errors=errors,
        )
    except Exception as exc:
        logger.error("portfolio_monitor: failed to create report page: %s", exc)
        errors.append(f"report_page_failed: {exc}")
        if status == "success":
            status = "partial"

    # ------------------------------------------------------------------
    # 10. Per-run Discord summary (every run — silent success is not acceptable)
    # ------------------------------------------------------------------
    try:
        await send_run_summary(
            run_id=run_id,
            run_timestamp=now_utc,
            positions_evaluated=positions_evaluated,
            flags=all_flags,
            status=status,
            report_url=report_url,
        )
    except Exception as exc:
        logger.error("portfolio_monitor: failed to send Discord summary: %s", exc)
        errors.append(f"discord_summary_failed: {exc}")
        if status == "success":
            status = "partial"

    # ------------------------------------------------------------------
    # 11. Write Execution Log (every run)
    # ------------------------------------------------------------------
    await _write_log(run_id=run_id, status=status, errors=errors, report_url=report_url)

    flag_strs = [f.description for f in all_flags]
    flag_types = list({f.flag_type.value for f in all_flags})
    critical_strs = [f.description for f in all_flags if f.severity == Severity.CRITICAL]

    result = RunSummary(
        run_id=run_id,
        status=status,
        market_open=market_open,
        positions_evaluated=positions_evaluated,
        flags_raised=flag_strs,
        flag_types=flag_types,
        critical_flags=critical_strs,
        andon_triggered=andon_result.triggered,
        andon_reason=andon_result.reason,
        report_url=report_url,
        errors=errors,
    )
    logger.info(
        "portfolio_monitor run complete: %s status=%s positions=%d flags=%d critical=%d",
        run_id,
        status,
        positions_evaluated,
        len(all_flags),
        len(critical_strs),
    )
    return result


async def _write_log(*, run_id: str, status: str, errors: list[str], report_url: str) -> None:
    """Write Execution Log row; errors here are logged but don't fail the run.

    Portfolio Monitor is a deterministic Stonky service (no LLM calls). Token
    fields are written as 0 to distinguish these rows from unmeasured LLM rows.
    """
    try:
        await nc.write_execution_log(
            run_id=run_id,
            agent="portfolio-monitor",
            model="stonky-engine",
            status=status,
            errors=errors or None,
            output_page_url=report_url,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0.0,
        )
    except Exception as exc:
        logger.error("portfolio_monitor: failed to write execution log: %s", exc)
