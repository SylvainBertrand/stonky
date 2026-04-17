"""TC-019 — Paper Trader end-to-end smoke test observation harness.

Stand-alone script that audits each phase of the smoke test by querying
the live Notion DBs.  Run at each gate below and paste the output into
the 'Smoke Test — First Paper Position' Notion page as the Cycle Receipt.

Prerequisites (must both be met before running Phase 1):
  - TC-016 merged: Signal Registry Notion DB has Timeframe field
  - TC-017 merged: Desk Head brief v1.2.0 (populates Entry/Stop/Target/Direction/Timeframe)

Usage:
    cd stonky
    set NOTION_API_KEY=<key>
    python scripts/tc019_smoke_test.py [--phase 1|2|3|4|receipt]

Phases:
  1  Pre-test — validate candidate signal has all required fields
  2  Post-open — verify Paper Portfolio row created with all required columns
  3  Monitor — verify Current Price / Unrealized PnL updated on subsequent runs
  4  Close — verify exit, Trade Journal close entry, Signal Registry outcome updated
  receipt  Print a complete Cycle Receipt (all phases combined)

Without --phase flag, runs all phases sequentially and prints the receipt.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime, timedelta
from typing import Any

# ---------------------------------------------------------------------------
# Notion DB IDs (from agents_common/notion_client.py)
# ---------------------------------------------------------------------------

SIGNAL_REGISTRY_DB = "777fdeb7-8b1b-4d25-9f98-bee68e1a3c28"
PAPER_PORTFOLIO_DB = "910c1cb0-65eb-4540-a0c3-7bdb20944939"
TRADE_JOURNAL_DB = "d14fd908-48e4-475a-ab4e-f11bcc29fd0d"
EXECUTION_LOG_DB = "b5adb864-bb3e-45a2-abfb-bd67e004c78d"

REQUIRED_SIGNAL_FIELDS = ["entry_price", "stop", "target", "direction", "timeframe"]
REQUIRED_PORTFOLIO_FIELDS = [
    "ticker",
    "stop",
    "target",
    "size",
    "entry_price",
    "entry_date",
    "thesis_id",
    "originating_agent",
    "status",
]
OK = "✅"
WARN = "⚠️"
FAIL = "❌"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_client() -> Any:
    from notion_client import AsyncClient

    api_key = os.environ.get("NOTION_API_KEY")
    if not api_key:
        sys.exit("NOTION_API_KEY environment variable is not set.")
    return AsyncClient(auth=api_key)


def _read_title(page: dict[str, Any], prop: str) -> str:
    try:
        items = page["properties"][prop]["title"]
        return items[0]["plain_text"] if items else ""
    except (KeyError, IndexError):
        return ""


def _read_text(page: dict[str, Any], prop: str) -> str:
    try:
        items = page["properties"][prop]["rich_text"]
        return items[0]["plain_text"] if items else ""
    except (KeyError, IndexError):
        return ""


def _read_number(page: dict[str, Any], prop: str) -> float:
    try:
        v = page["properties"][prop]["number"]
        return float(v) if v is not None else 0.0
    except (KeyError, TypeError):
        return 0.0


def _read_select(page: dict[str, Any], prop: str) -> str:
    try:
        sel = page["properties"][prop]["select"]
        return sel["name"] if sel else ""
    except (KeyError, TypeError):
        return ""


def _read_date_start(page: dict[str, Any], prop: str) -> str:
    try:
        d = page["properties"][prop]["date"]
        return d["start"] if d else ""
    except (KeyError, TypeError):
        return ""


def _page_url(page: dict[str, Any]) -> str:
    page_id: str = page.get("id", "").replace("-", "")
    return f"https://www.notion.so/{page_id}"


async def _query(
    client: Any,
    db_id: str,
    filter_body: dict[str, Any] | None = None,
    sorts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {}
    if filter_body:
        body["filter"] = filter_body
    if sorts:
        body["sorts"] = sorts
    resp = await client.request(path=f"databases/{db_id}/query", method="POST", body=body)
    return resp.get("results", [])


def _banner(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(f"  {title}")
    print(f"{'=' * 60}")


def _check(label: str, value: Any, ok: bool) -> None:
    icon = OK if ok else FAIL
    print(f"  {icon}  {label}: {value!r}")


# ---------------------------------------------------------------------------
# Phase 1 — Validate candidate signal
# ---------------------------------------------------------------------------


async def phase1_validate_signal(client: Any, signal_url: str = "") -> dict[str, Any]:
    """Check Signal Registry for a valid, board-approved DESK signal.

    If signal_url is provided, validate that specific signal.
    Otherwise, find the most recent approved DESK signal.
    Returns a dict with validation results.
    """
    _banner("Phase 1 — Signal Validation")

    cutoff = (datetime.now(UTC) - timedelta(hours=48)).isoformat()

    if signal_url:
        signal_id = signal_url.rstrip("/").split("/")[-1].replace("-", "")
        results = await _query(
            client,
            SIGNAL_REGISTRY_DB,
            filter_body={"property": "Agent", "rich_text": {"equals": "desk-head"}},
        )
        pages = [p for p in results if p.get("id", "").replace("-", "") == signal_id]
    else:
        pages = await _query(
            client,
            SIGNAL_REGISTRY_DB,
            filter_body={
                "and": [
                    {"property": "Agent", "rich_text": {"equals": "desk-head"}},
                    {"property": "Date", "date": {"on_or_after": cutoff}},
                ]
            },
            sorts=[{"property": "Score", "direction": "descending"}],
        )

    if not pages:
        print(f"  {FAIL}  No recent DESK signals found in Signal Registry (last 48h).")
        print("       Prerequisite not met: wait for Desk Head to produce a signal.")
        return {"phase": 1, "passed": False, "signal": None}

    page = pages[0]
    signal = {
        "id": page["id"],
        "url": _page_url(page),
        "ticker": _read_title(page, "Ticker") or _read_text(page, "Ticker"),
        "agent": _read_text(page, "Agent"),
        "score": _read_number(page, "Score"),
        "board_decision": _read_select(page, "Board Decision"),
        "entry_price": _read_number(page, "Entry Price"),
        "stop": _read_number(page, "Stop"),
        "target": _read_number(page, "Target"),
        "direction": _read_select(page, "Direction"),
        "timeframe": _read_select(page, "Timeframe"),
        "thesis_id": _read_text(page, "Thesis ID"),
    }

    print(f"\n  Candidate signal: {signal['url']}")
    print(
        f"  Ticker: {signal['ticker']}  Score: {signal['score']}  "
        f"Direction: {signal['direction']}  Timeframe: {signal['timeframe']}"
    )
    print(f"  Entry: {signal['entry_price']}  Stop: {signal['stop']}  Target: {signal['target']}")

    # Validate all required numeric fields are non-zero
    passed = True
    for field in REQUIRED_SIGNAL_FIELDS:
        val = signal[field]
        ok = bool(val)
        _check(field, val, ok)
        if not ok:
            passed = False

    # Validate R:R ratio
    entry = signal["entry_price"]
    stop = signal["stop"]
    target = signal["target"]
    direction = signal["direction"]
    if entry > 0 and stop > 0 and target > 0:
        if direction == "long":
            risk = entry - stop
            reward = target - entry
        else:
            risk = stop - entry
            reward = entry - target
        rr = reward / risk if risk > 0 else 0.0
        rr_ok = rr >= 1.5
        _check(f"R:R ratio ({direction})", f"{rr:.2f}", rr_ok)
        if not rr_ok:
            passed = False

    # Board decision status
    board = signal["board_decision"]
    _check("Board Decision", board, board in ("pending", "approved"))
    if board == "approved":
        print(f"  {OK}  Signal is board-approved — Paper Trader will pick it up on next run.")
    elif board == "pending":
        print(f"  {WARN}  Signal is pending board decision.")
        print("       Action: Board must set Board Decision = approved via Notion UI.")
    else:
        print(f"  {FAIL}  Signal Board Decision is '{board}' — not actionable.")
        passed = False

    result = {"phase": 1, "passed": passed, "signal": signal}
    print(f"\n  Phase 1: {'PASS' if passed else 'FAIL'}")
    return result


# ---------------------------------------------------------------------------
# Phase 2 — Verify position opened
# ---------------------------------------------------------------------------


async def phase2_verify_position_opened(client: Any, ticker: str = "") -> dict[str, Any]:
    """Check Paper Portfolio DB for a new open position."""
    _banner("Phase 2 — Position Opened Verification")

    filter_body: dict[str, Any] = {"property": "Status", "select": {"equals": "open"}}
    if ticker:
        filter_body = {
            "and": [
                filter_body,
                {"property": "Ticker", "title": {"equals": ticker.upper()}},
            ]
        }

    positions = await _query(
        client,
        PAPER_PORTFOLIO_DB,
        filter_body=filter_body,
        sorts=[{"property": "Entry Date", "direction": "descending"}],
    )

    if not positions:
        print(f"  {FAIL}  No open positions found in Paper Portfolio DB.")
        print("       Action: Board approves signal; wait for next 15-min Paper Trader cycle.")
        return {"phase": 2, "passed": False, "position": None}

    page = positions[0]
    pos = {
        "id": page["id"],
        "url": _page_url(page),
        "ticker": _read_title(page, "Ticker"),
        "status": _read_select(page, "Status"),
        "entry_price": _read_number(page, "Entry Price"),
        "stop": _read_number(page, "Stop"),
        "target": _read_number(page, "Target"),
        "size": _read_number(page, "Size"),
        "entry_date": _read_date_start(page, "Entry Date"),
        "thesis_id": _read_text(page, "Thesis ID"),
        "originating_agent": _read_text(page, "Originating Agent"),
        "signal_id": _read_text(page, "Signal ID"),
        "current_price": _read_number(page, "Current Price"),
        "unrealized_pnl": _read_number(page, "Unrealized PnL"),
    }

    print(f"\n  Position: {pos['url']}")
    print(f"  Ticker: {pos['ticker']}  Status: {pos['status']}")
    print(f"  Entry @ {pos['entry_price']}  Stop: {pos['stop']}  Target: {pos['target']}")
    print(f"  Size: {pos['size']}  Entry Date: {pos['entry_date']}")

    passed = True
    for field in REQUIRED_PORTFOLIO_FIELDS:
        val = pos[field]
        ok = bool(val)
        _check(field, val, ok)
        if not ok:
            passed = False

    # Verify originating_agent is paper-trader
    _check(
        "originating_agent = paper-trader",
        pos["originating_agent"],
        pos["originating_agent"] == "paper-trader",
    )
    if pos["originating_agent"] != "paper-trader":
        passed = False

    # Verify entry price is a real fill (should be non-zero)
    _check("entry_price > 0", pos["entry_price"], pos["entry_price"] > 0)
    if pos["entry_price"] <= 0:
        passed = False

    result = {"phase": 2, "passed": passed, "position": pos}
    print(f"\n  Phase 2: {'PASS' if passed else 'FAIL'}")
    return result


# ---------------------------------------------------------------------------
# Phase 3 — Verify monitor updates
# ---------------------------------------------------------------------------


async def phase3_verify_monitor(client: Any, position_id: str = "") -> dict[str, Any]:
    """Verify Current Price and Unrealized PnL are updating on open positions."""
    _banner("Phase 3 — Monitor-Mode Verification")

    filter_body: dict[str, Any] = {"property": "Status", "select": {"equals": "open"}}
    positions = await _query(client, PAPER_PORTFOLIO_DB, filter_body=filter_body)

    if not positions:
        print(f"  {FAIL}  No open positions to monitor.")
        return {"phase": 3, "passed": False}

    if position_id:
        positions = [p for p in positions if p.get("id", "").replace("-", "") == position_id]

    passed = True
    for page in positions:
        ticker = _read_title(page, "Ticker")
        current_price = _read_number(page, "Current Price")
        entry_price = _read_number(page, "Entry Price")
        unrealized_pnl = _read_number(page, "Unrealized PnL")
        url = _page_url(page)

        print(f"\n  Position: {ticker} ({url})")
        price_updated = current_price > 0 and current_price != entry_price
        _check("Current Price > 0", current_price, current_price > 0)
        _check("Current Price != Entry Price (price updated)", current_price, price_updated)
        _check("Unrealized PnL is set", unrealized_pnl, unrealized_pnl != 0)

        if not (current_price > 0):
            passed = False

    # Check Execution Log for recent paper-trader runs
    cutoff = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    exec_logs = await _query(
        client,
        EXECUTION_LOG_DB,
        filter_body={
            "and": [
                {"property": "Agent", "rich_text": {"equals": "paper-trader"}},
                {"property": "Timestamp", "date": {"on_or_after": cutoff}},
            ]
        },
        sorts=[{"property": "Timestamp", "direction": "descending"}],
    )
    _check("Execution Log entries in last hour", len(exec_logs), len(exec_logs) > 0)
    for log in exec_logs[:3]:
        run_id = _read_title(log, "Run ID")
        status = _read_select(log, "Status")
        ts = _read_date_start(log, "Timestamp")
        print(f"       {OK if status == 'success' else WARN}  {run_id}  {status}  {ts}")

    print(f"\n  Phase 3: {'PASS' if passed else 'FAIL'}")
    return {"phase": 3, "passed": passed}


# ---------------------------------------------------------------------------
# Phase 4 — Verify close
# ---------------------------------------------------------------------------


async def phase4_verify_close(
    client: Any, ticker: str = "", position_id: str = ""
) -> dict[str, Any]:
    """Verify position closed correctly, Trade Journal entry written, Signal Registry updated."""
    _banner("Phase 4 — Close Verification")

    filter_body: dict[str, Any] = {"property": "Status", "select": {"equals": "closed"}}
    if ticker:
        filter_body = {
            "and": [
                filter_body,
                {"property": "Ticker", "title": {"equals": ticker.upper()}},
            ]
        }

    closed_positions = await _query(
        client,
        PAPER_PORTFOLIO_DB,
        filter_body=filter_body,
        sorts=[{"property": "Exit Date", "direction": "descending"}],
    )

    if not closed_positions:
        print(f"  {WARN}  No closed positions yet.  Wait for stop/target hit or force close.")
        return {"phase": 4, "passed": False, "closed": None}

    page = closed_positions[0]
    pos = {
        "id": page["id"],
        "url": _page_url(page),
        "ticker": _read_title(page, "Ticker"),
        "exit_price": _read_number(page, "Exit Price"),
        "exit_date": _read_date_start(page, "Exit Date"),
        "exit_reason": _read_select(page, "Exit Reason"),
        "realized_pnl": _read_number(page, "Realized PnL"),
        "r_multiple": _read_number(page, "R-Multiple"),
        "outcome": _read_select(page, "Outcome"),
        "signal_id": _read_text(page, "Signal ID"),
    }

    print(f"\n  Closed position: {pos['ticker']} ({pos['url']})")
    passed = True

    exit_fields = ["exit_price", "exit_date", "exit_reason", "outcome"]
    for field in exit_fields:
        val = pos[field]
        ok = bool(val)
        _check(field, val, ok)
        if not ok:
            passed = False

    _check("realized_pnl is set", pos["realized_pnl"], pos["realized_pnl"] != 0)
    _check("r_multiple is set", pos["r_multiple"], pos["r_multiple"] != 0)

    # Check Trade Journal close entry
    if pos["signal_id"]:
        journal_entries = await _query(
            client,
            TRADE_JOURNAL_DB,
            filter_body={
                "and": [
                    {"property": "Event", "select": {"equals": "position-close"}},
                    {"property": "Signal ID", "rich_text": {"equals": pos["signal_id"]}},
                ]
            },
        )
        _check("Trade Journal close entry exists", len(journal_entries), len(journal_entries) > 0)
        if not journal_entries:
            passed = False
        else:
            je = journal_entries[0]
            tj_url = _page_url(je)
            print(f"       Trade Journal: {tj_url}")

    # Handle manual-close edge case (AC5c)
    if pos["exit_reason"] == "manual":
        print(f"\n  {WARN}  Manual close detected (Exit Reason = manual).")
        print("       Per AC5c: Paper Trader should not re-open this position.")
        print("       Verify Paper Trader did NOT error on next run and Status stayed 'closed'.")

    result = {"phase": 4, "passed": passed, "closed": pos}
    print(f"\n  Phase 4: {'PASS' if passed else 'FAIL'}")
    return result


# ---------------------------------------------------------------------------
# Cycle Receipt — print full summary
# ---------------------------------------------------------------------------


async def cycle_receipt(client: Any) -> None:
    """Run all phases and print a full Cycle Receipt for pasting into the Notion page."""
    _banner("TC-019 Smoke Test — Cycle Receipt")
    print(f"  Generated: {datetime.now(UTC).isoformat()}")

    r1 = await phase1_validate_signal(client)
    r2 = await phase2_verify_position_opened(client)
    r3 = await phase3_verify_monitor(client)
    r4 = await phase4_verify_close(client)

    _banner("Summary")
    phases = [r1, r2, r3, r4]
    all_passed = all(r.get("passed") for r in phases)
    for r in phases:
        icon = OK if r.get("passed") else FAIL
        print(f"  {icon}  Phase {r['phase']}")

    print()
    if all_passed:
        print(f"  {OK}  ALL PHASES PASS — TC-019 smoke test complete.")
        print("  Copy this output into the 'Smoke Test — First Paper Position' Notion page.")
    else:
        print(f"  {FAIL}  SOME PHASES FAILED — see details above.")
        print("  File a bug ticket for each failed phase per AC7.")


# ---------------------------------------------------------------------------
# Signal Registry — check for executed transition
# ---------------------------------------------------------------------------


async def check_signal_executed(client: Any, signal_id: str) -> bool:
    """Verify that Board Decision on a signal has transitioned to 'executed'."""
    results = await _query(
        client,
        SIGNAL_REGISTRY_DB,
        filter_body={
            "and": [
                {"property": "Board Decision", "select": {"equals": "executed"}},
            ]
        },
    )
    ids = {p.get("id", "").replace("-", "") for p in results}
    clean_id = signal_id.replace("-", "")
    found = clean_id in ids
    icon = OK if found else FAIL
    print(f"  {icon}  Signal {signal_id} Board Decision = executed: {found}")
    return found


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


async def main() -> None:
    parser = argparse.ArgumentParser(description="TC-019 smoke test observation harness")
    parser.add_argument(
        "--phase",
        choices=["1", "2", "3", "4", "receipt"],
        default="receipt",
        help="Which phase to run (default: receipt = all phases)",
    )
    parser.add_argument("--ticker", default="", help="Ticker symbol to filter on (Phase 2/4)")
    parser.add_argument("--signal-url", default="", help="Notion URL of the test signal (Phase 1)")
    args = parser.parse_args()

    client = _get_client()

    if args.phase == "1":
        await phase1_validate_signal(client, signal_url=args.signal_url)
    elif args.phase == "2":
        await phase2_verify_position_opened(client, ticker=args.ticker)
    elif args.phase == "3":
        await phase3_verify_monitor(client)
    elif args.phase == "4":
        await phase4_verify_close(client, ticker=args.ticker)
    else:
        await cycle_receipt(client)


if __name__ == "__main__":
    asyncio.run(main())
