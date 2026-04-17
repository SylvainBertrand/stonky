#!/usr/bin/env python3
"""TC-019 Paper Trader Smoke Test Observer.

Queries Notion databases to audit and verify the Paper Trader end-to-end
cycle (Signal → Approval → Execute → Monitor → Close).  Run this script
at each AC checkpoint during the smoke test.

Usage (from repo root or backend/):
    cd backend
    uv run python scripts/smoke_test_observer.py
    uv run python scripts/smoke_test_observer.py --days 14

The script does NOT modify any Notion data — read-only throughout.

Notion databases queried:
  Signal Registry  — collection://777fdeb7-8b1b-4d25-9f98-bee68e1a3c28
  Paper Portfolio  — collection://910c1cb0-65eb-4540-a0c3-7bdb20944939
  Trade Journal    — collection://d14fd908-48e4-475a-ab4e-f11bcc29fd0d
  Execution Log    — collection://b5adb864-bb3e-45a2-abfb-bd67e004c78d

References: TC-019 acceptance criteria
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

# ---------------------------------------------------------------------------
# Notion DB constants (UUID part of collection:// URIs)
# ---------------------------------------------------------------------------

SIGNAL_REGISTRY_DB = "777fdeb7-8b1b-4d25-9f98-bee68e1a3c28"
PAPER_PORTFOLIO_DB = "910c1cb0-65eb-4540-a0c3-7bdb20944939"
TRADE_JOURNAL_DB = "d14fd908-48e4-475a-ab4e-f11bcc29fd0d"
EXECUTION_LOG_DB = "b5adb864-bb3e-45a2-abfb-bd67e004c78d"

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"

# Required non-zero AC3 fields for a valid open position
_AC3_REQUIRED_NONZERO = ["entry_price", "stop", "target", "size"]
_AC3_REQUIRED_NONEMPTY = ["ticker", "status", "direction", "entry_date", "originating_agent"]

# Required AC5 close fields
_AC5_REQUIRED_NONZERO = ["exit_price", "realized_pnl"]
_AC5_REQUIRED_NONEMPTY = ["exit_reason", "exit_date"]


# ---------------------------------------------------------------------------
# Environment / key loading
# ---------------------------------------------------------------------------


def _load_api_key() -> str:
    key = os.environ.get("NOTION_API_KEY", "")
    if not key:
        # Try root .env (two dirs up from backend/scripts/)
        env_path = Path(__file__).resolve().parent.parent.parent / ".env"
        if env_path.exists():
            for raw in env_path.read_text(encoding="utf-8").splitlines():
                stripped = raw.strip()
                if stripped.startswith("NOTION_API_KEY=") and not stripped.startswith("#"):
                    key = stripped.split("=", 1)[1].strip().strip('"').strip("'")
                    break
    if not key:
        print("ERROR: NOTION_API_KEY not set. Set it in env or repo-root .env.")
        sys.exit(1)
    return key


def _client(api_key: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=NOTION_BASE,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        },
        timeout=30.0,
    )


# ---------------------------------------------------------------------------
# Notion property readers
# ---------------------------------------------------------------------------


def _title(page: dict[str, Any], prop: str) -> str:
    try:
        items = page["properties"][prop]["title"]
        return items[0]["plain_text"] if items else ""
    except (KeyError, IndexError):
        return ""


def _text(page: dict[str, Any], prop: str) -> str:
    try:
        items = page["properties"][prop]["rich_text"]
        return items[0]["plain_text"] if items else ""
    except (KeyError, IndexError):
        return ""


def _num(page: dict[str, Any], prop: str) -> float | None:
    try:
        v = page["properties"][prop]["number"]
        return float(v) if v is not None else None
    except (KeyError, TypeError):
        return None


def _sel(page: dict[str, Any], prop: str) -> str:
    try:
        sel = page["properties"][prop]["select"]
        return sel["name"] if sel else ""
    except (KeyError, TypeError):
        return ""


def _date(page: dict[str, Any], prop: str) -> str:
    try:
        d = page["properties"][prop]["date"]
        return d["start"] if d else ""
    except (KeyError, TypeError):
        return ""


def _page_url(page: dict[str, Any]) -> str:
    return f"https://www.notion.so/{page.get('id', '').replace('-', '')}"


# ---------------------------------------------------------------------------
# Low-level Notion query
# ---------------------------------------------------------------------------


async def _query(
    client: httpx.AsyncClient,
    db_id: str,
    filter_body: dict[str, Any] | None = None,
    sorts: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {}
    if filter_body:
        body["filter"] = filter_body
    if sorts:
        body["sorts"] = sorts
    resp = await client.post(f"/databases/{db_id}/query", json=body)
    resp.raise_for_status()
    data = resp.json()
    pages = data.get("results", [])
    # Handle pagination (has_more)
    while data.get("has_more") and data.get("next_cursor"):
        body["start_cursor"] = data["next_cursor"]
        resp = await client.post(f"/databases/{db_id}/query", json=body)
        resp.raise_for_status()
        data = resp.json()
        pages.extend(data.get("results", []))
    return pages


# ---------------------------------------------------------------------------
# Domain parsers
# ---------------------------------------------------------------------------


def _parse_signal(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page["id"],
        "url": _page_url(page),
        "ticker": _title(page, "Ticker") or _text(page, "Ticker"),
        "board_decision": _sel(page, "Board Decision"),
        "agent": _text(page, "Agent"),
        "date": _date(page, "Date"),
        "score": _num(page, "Score"),
        "entry_price": _num(page, "Entry Price"),
        "stop": _num(page, "Stop"),
        "target": _num(page, "Target"),
        "direction": _sel(page, "Direction"),
        "timeframe": _sel(page, "Timeframe"),
        "thesis_id": _text(page, "Thesis ID"),
    }


def _parse_position(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page["id"],
        "url": _page_url(page),
        "ticker": _title(page, "Ticker"),
        "status": _sel(page, "Status"),
        "entry_price": _num(page, "Entry Price"),
        "stop": _num(page, "Stop"),
        "target": _num(page, "Target"),
        "size": _num(page, "Size"),
        "direction": _sel(page, "Direction"),
        "entry_date": _date(page, "Entry Date"),
        "signal_id": _text(page, "Signal ID"),
        "thesis_id": _text(page, "Thesis ID"),
        "originating_agent": _text(page, "Originating Agent"),
        "current_price": _num(page, "Current Price"),
        "unrealized_pnl": _num(page, "Unrealized PnL"),
        "exit_price": _num(page, "Exit Price"),
        "exit_date": _date(page, "Exit Date"),
        "exit_reason": _sel(page, "Exit Reason"),
        "realized_pnl": _num(page, "Realized PnL"),
        "r_multiple": _num(page, "R-Multiple"),
        "outcome": _sel(page, "Outcome"),
    }


def _parse_log(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "run_id": _title(page, "Run ID"),
        "agent": _text(page, "Agent"),
        "timestamp": _date(page, "Timestamp"),
        "model": _text(page, "Model"),
        "status": _sel(page, "Status"),
        "errors": _text(page, "Errors"),
        "output_url": _text(page, "Output Page URL"),
        "url": _page_url(page),
    }


def _parse_journal(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "ticker": _title(page, "Ticker"),
        "event": _sel(page, "Event"),
        "signal_id": _text(page, "Signal ID"),
        "entry_price": _num(page, "Entry Price"),
        "exit_price": _num(page, "Exit Price"),
        "realized_pnl": _num(page, "Realized PnL"),
        "r_multiple": _num(page, "R-Multiple"),
        "outcome": _sel(page, "Outcome"),
        "open_date": _date(page, "Open Date"),
        "close_date": _date(page, "Close Date"),
        "url": _page_url(page),
    }


# ---------------------------------------------------------------------------
# Report helpers
# ---------------------------------------------------------------------------

SEP = "─" * 72


def _hdr(title: str) -> None:
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def _field(label: str, value: Any, required: bool = False) -> str:
    if value is None or value == "" or value == 0.0:
        marker = "✗ MISSING" if required else "─ empty"
        return f"    {label:<28} {marker}"
    return f"    {label:<28} ✓  {value}"


def _check(label: str, ok: bool, detail: str = "") -> None:
    icon = "✓" if ok else "✗"
    suffix = f"  [{detail}]" if detail else ""
    print(f"  {icon}  {label}{suffix}")


# ---------------------------------------------------------------------------
# Prerequisite checks (AC 1)
# ---------------------------------------------------------------------------


def _check_prerequisites() -> None:
    _hdr("AC 1 — Prerequisites")
    for ticket, expected_branch in [
        ("TC-016", "feature/tc-016"),
        ("TC-017", "feature/tc-017"),
    ]:
        try:
            result = subprocess.run(
                ["gh", "pr", "list", "--state", "merged", "--search", ticket, "--limit", "5"],
                capture_output=True,
                text=True,
                timeout=15,
            )
            merged = ticket.lower() in result.stdout.lower()
        except Exception as e:
            merged = False
            print(f"    gh CLI error for {ticket}: {e}")
        _check(f"{ticket} merged to stonky main", merged, "gh pr list")

    print()
    print("  NOTE: If TC-016/TC-017 are not merged, live verification is blocked.")
    print("        The observation harness (this script) is still usable for AC 3–6")
    print("        once prerequisites are met.")


# ---------------------------------------------------------------------------
# Signal audit (AC 2 + AC 3 upstream)
# ---------------------------------------------------------------------------


async def _audit_signals(
    client: httpx.AsyncClient,
    days: int,
) -> list[dict[str, Any]]:
    _hdr(f"Signal Registry — last {days} days (AC 2 signal selection)")
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    pages = await _query(
        client,
        SIGNAL_REGISTRY_DB,
        filter_body={"property": "Date", "date": {"on_or_after": cutoff}},
        sorts=[{"property": "Date", "direction": "descending"}],
    )
    signals = [_parse_signal(p) for p in pages]
    if not signals:
        print("  No signals found in window.")
        return []

    # Group by Board Decision for summary
    by_decision: dict[str, list[dict[str, Any]]] = {}
    for s in signals:
        bd = s["board_decision"] or "unset"
        by_decision.setdefault(bd, []).append(s)

    print(f"  Total signals: {len(signals)}")
    for dec, group in sorted(by_decision.items()):
        print(f"    {dec}: {len(group)}")
    print()

    # Detail rows (approved + executed, most relevant)
    relevant = [s for s in signals if s["board_decision"] in ("approved", "executed", "pending")]
    if relevant:
        print("  Relevant signals (approved / executed / pending):")
        for s in relevant:
            has_all = all([s["stop"], s["target"], s["direction"], s["timeframe"]])
            fields_ok = "✓ fields OK" if has_all else "⚠ fields INCOMPLETE"
            print(
                f"    [{s['board_decision']:>9}] {s['ticker']:<6}  score={s['score']}  "
                f"{fields_ok}  {s['url']}"
            )
            if not has_all:
                missing = []
                for f in ("stop", "target", "direction", "timeframe"):
                    if not s[f]:
                        missing.append(f)
                print(f"               Missing: {', '.join(missing)}")
    else:
        print("  No approved/executed/pending signals in window.")

    return signals


# ---------------------------------------------------------------------------
# Portfolio audit (AC 3 + AC 4 + AC 5)
# ---------------------------------------------------------------------------


async def _audit_portfolio(client: httpx.AsyncClient, days: int) -> list[dict[str, Any]]:
    _hdr(f"Paper Portfolio DB — last {days} days (AC 3 / AC 4 / AC 5)")

    # Fetch all positions (open + closed) created in window
    # Notion doesn't have a created_at filter on DB queries without a date property,
    # so we fetch all and filter in Python by entry_date
    pages = await _query(client, PAPER_PORTFOLIO_DB)
    positions = [_parse_position(p) for p in pages]

    cutoff = datetime.now(UTC) - timedelta(days=days)
    recent = [
        p
        for p in positions
        if p["entry_date"] and datetime.fromisoformat(p["entry_date"]) >= cutoff
    ]

    if not recent:
        print(f"  No positions with entry_date in last {days} days.")
        print("  (If Paper Portfolio DB is empty, the smoke test has not started yet.)")
        return positions

    open_pos = [p for p in recent if p["status"] == "open"]
    closed_pos = [p for p in recent if p["status"] == "closed"]
    print(
        f"  Positions in window: {len(recent)}  (open: {len(open_pos)}, closed: {len(closed_pos)})"
    )

    for pos in recent:
        status_icon = "🟢" if pos["status"] == "open" else "🔴"
        print(f"\n  {status_icon} {pos['ticker']} [{pos['status']}]  {pos['url']}")
        _print_ac3_check(pos)
        if pos["status"] == "open":
            _print_ac4_check(pos)
        elif pos["status"] == "closed":
            _print_ac5_check(pos)

    return positions


def _print_ac3_check(pos: dict[str, Any]) -> None:
    print("    AC3 — Open position fields:")
    for f in _AC3_REQUIRED_NONZERO:
        v = pos.get(f)
        ok = v is not None and v != 0.0
        print(_field(f, v, required=True) + ("" if ok else "  ← FAIL"))
    for f in _AC3_REQUIRED_NONEMPTY:
        v = pos.get(f, "")
        ok = bool(v)
        print(_field(f, v, required=True) + ("" if ok else "  ← FAIL"))

    agent_ok = pos["originating_agent"] == "paper-trader"
    if not agent_ok:
        print(f"    {'originating_agent':<28} ✗ WRONG: '{pos['originating_agent']}'  ← FAIL")


def _print_ac4_check(pos: dict[str, Any]) -> None:
    print("    AC4 — Monitor-mode fields:")
    print(_field("current_price", pos["current_price"]))
    print(_field("unrealized_pnl", pos["unrealized_pnl"]))
    note = "(These update every Paper Trader run — check Execution Log for cycle count)"
    print(f"    {note}")


def _print_ac5_check(pos: dict[str, Any]) -> None:
    print("    AC5 — Close path fields:")
    for f in _AC5_REQUIRED_NONZERO:
        v = pos.get(f)
        ok = v is not None and v != 0.0
        print(_field(f, v, required=True) + ("" if ok else "  ← FAIL"))
    for f in _AC5_REQUIRED_NONEMPTY:
        v = pos.get(f, "")
        ok = bool(v)
        print(_field(f, v, required=True) + ("" if ok else "  ← FAIL"))
    # R-Multiple can be negative (loss), so just check it's populated
    r = pos.get("r_multiple")
    ok_r = r is not None
    print(_field("r_multiple", r, required=True) + ("" if ok_r else "  ← FAIL"))
    print(_field("outcome", pos.get("outcome", ""), required=True))


# ---------------------------------------------------------------------------
# Execution Log audit (AC 3 + AC 4 — mandatory per-run entry)
# ---------------------------------------------------------------------------


async def _audit_execution_log(client: httpx.AsyncClient, days: int) -> None:
    _hdr(f"Execution Log — paper-trader runs in last {days} days (AC 3 / AC 4)")
    cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    pages = await _query(
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
    logs = [_parse_log(p) for p in pages]

    if not logs:
        print("  No paper-trader Execution Log entries in window.")
        print("  (Expected: at least one entry per 15-min cycle during NYSE hours)")
        return

    success = sum(1 for l in logs if l["status"] == "success")
    partial = sum(1 for l in logs if l["status"] == "partial")
    failed = sum(1 for l in logs if l["status"] == "failed")
    print(f"  Total runs: {len(logs)}  (success: {success}, partial: {partial}, failed: {failed})")
    print()

    # Show last 10 runs
    for log in logs[:10]:
        err_flag = "  ⚠" if log["errors"] else ""
        print(f"  [{log['timestamp'][:19]}]  {log['status']:<8}  {log['run_id']}{err_flag}")
        if log["errors"]:
            print(f"    Errors: {log['errors'][:120]}")

    if len(logs) > 10:
        print(f"  ... and {len(logs) - 10} more runs")


# ---------------------------------------------------------------------------
# Trade Journal audit (AC 5 — close event)
# ---------------------------------------------------------------------------


async def _audit_trade_journal(client: httpx.AsyncClient, days: int) -> None:
    _hdr(f"Trade Journal — last {days} days (AC 5 — close path)")
    # Trade Journal uses Open Date / Close Date; filter on recently active rows
    pages = await _query(
        client,
        TRADE_JOURNAL_DB,
        sorts=[{"timestamp": "last_edited_time", "direction": "descending"}],
    )

    # Filter by recency in Python (no reliable date filter without knowing event type)
    entries: list[dict[str, Any]] = []
    for p in pages:
        j = _parse_journal(p)
        date_str = j["close_date"] or j["open_date"]
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str)
                if dt >= datetime.now(UTC) - timedelta(days=days):
                    entries.append(j)
            except ValueError:
                pass

    if not entries:
        print(f"  No Trade Journal entries in last {days} days.")
        return

    opens = [e for e in entries if e["event"] == "position-open"]
    closes = [e for e in entries if e["event"] == "position-close"]
    print(f"  Entries in window: {len(entries)}  (opens: {len(opens)}, closes: {len(closes)})")
    print()

    for e in sorted(entries, key=lambda x: x["close_date"] or x["open_date"], reverse=True)[:10]:
        date_str = e["close_date"] or e["open_date"]
        pnl_str = f"pnl={e['realized_pnl']:.2f}" if e["realized_pnl"] is not None else ""
        r_str = f"R={e['r_multiple']:.2f}" if e["r_multiple"] is not None else ""
        outcome = e.get("outcome", "")
        print(
            f"  [{date_str[:19]}]  {e['event']:<16}  {e['ticker']:<6}  "
            f"{pnl_str}  {r_str}  {outcome}  {e['url']}"
        )


# ---------------------------------------------------------------------------
# AC 6 — Chain summary
# ---------------------------------------------------------------------------


async def _print_chain_summary(
    signals: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    client: httpx.AsyncClient,
    days: int,
) -> None:
    _hdr("AC 6 — Complete Chain Summary")

    executed_signals = [s for s in signals if s["board_decision"] == "executed"]
    open_pos = [p for p in positions if p["status"] == "open"]
    closed_pos = [p for p in positions if p["status"] == "closed"]

    cutoff = datetime.now(UTC) - timedelta(days=days)

    # Re-fetch execution log count for chain check
    pages = await _query(
        client,
        EXECUTION_LOG_DB,
        filter_body={
            "and": [
                {"property": "Agent", "rich_text": {"equals": "paper-trader"}},
                {"property": "Timestamp", "date": {"on_or_after": cutoff.isoformat()}},
            ]
        },
    )
    log_count = len(pages)

    _check(
        "Signal approved (Board Decision = approved)",
        any(s["board_decision"] in ("approved", "executed") for s in signals),
    )
    _check("Position opened (Paper Portfolio row created)", len(open_pos) + len(closed_pos) > 0)
    _check("Signal marked executed (Board Decision → executed)", len(executed_signals) > 0)
    _check(
        "Position monitored (Current Price / Unrealized PnL populated)",
        any(p["current_price"] not in (None, 0.0) for p in open_pos),
    )
    _check("Execution Log written per run", log_count > 0, f"{log_count} runs logged")
    _check("Position closed (closed row exists)", len(closed_pos) > 0)

    if closed_pos:
        p = closed_pos[0]
        _check(
            "Exit Price / Exit Date / Exit Reason populated",
            all([p["exit_price"], p["exit_date"], p["exit_reason"]]),
        )
        _check(
            "Realized PnL / R-Multiple populated",
            all([p["realized_pnl"] is not None, p["r_multiple"] is not None]),
        )

    print()
    print("  Discord notifications must be verified manually via Discord channel history.")
    print("  Trade Journal close entry verified in Trade Journal section above.")
    print()
    print("  Paste all artifact URLs in a 'Cycle Receipt' comment on TC-019 when complete.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def _main(days: int) -> None:
    now_str = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
    print(f"\n{'═' * 72}")
    print("  TC-019 Paper Trader Smoke Test Observer")
    print(f"  Run at: {now_str}  |  Window: last {days} days")
    print(f"{'═' * 72}")

    api_key = _load_api_key()
    async with _client(api_key) as client:
        _check_prerequisites()
        signals = await _audit_signals(client, days)
        positions = await _audit_portfolio(client, days)
        await _audit_execution_log(client, days)
        await _audit_trade_journal(client, days)
        await _print_chain_summary(signals, positions, client, days)

    print(f"\n{'═' * 72}")
    print(f"  Observer run complete at {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"{'═' * 72}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="TC-019 Paper Trader Smoke Test Observer")
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days back to query (default: 7)",
    )
    args = parser.parse_args()
    asyncio.run(_main(args.days))


if __name__ == "__main__":
    main()
