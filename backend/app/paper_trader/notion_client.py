"""Notion API client for the Paper Trader service.

Handles all reads and writes to:
  - Signal Registry    (collection://777fdeb7-8b1b-4d25-9f98-bee68e1a3c28)
  - Paper Portfolio DB (collection://910c1cb0-65eb-4540-a0c3-7bdb20944939)
  - Trade Journal      (collection://d14fd908-48e4-475a-ab4e-f11bcc29fd0d)
  - Execution Log      (collection://b5adb864-bb3e-45a2-abfb-bd67e004c78d)

Uses the official notion-client library (async). All DB IDs are hard-coded as
module-level constants so they can be patched in tests.

References:
  - Brief: briefs/paper-trader.yaml v1.0.0
  - Ticket: TC-007 Acceptance Criteria #1, #4, #5, #6
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from notion_client import AsyncClient

from app.config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Database IDs (UUID part of collection:// URIs from the brief)
# ---------------------------------------------------------------------------

SIGNAL_REGISTRY_DB = "777fdeb7-8b1b-4d25-9f98-bee68e1a3c28"
PAPER_PORTFOLIO_DB = "910c1cb0-65eb-4540-a0c3-7bdb20944939"
TRADE_JOURNAL_DB = "d14fd908-48e4-475a-ab4e-f11bcc29fd0d"
EXECUTION_LOG_DB = "b5adb864-bb3e-45a2-abfb-bd67e004c78d"


def _get_client() -> AsyncClient:
    """Return an authenticated Notion AsyncClient."""
    if not settings.notion_api_key:
        raise RuntimeError(
            "NOTION_API_KEY is not configured. Set it in .env or environment variables."
        )
    return AsyncClient(auth=settings.notion_api_key)


# ---------------------------------------------------------------------------
# Property helpers
# ---------------------------------------------------------------------------


def _text(value: str) -> dict[str, Any]:
    return {"rich_text": [{"text": {"content": value}}]}


def _title(value: str) -> dict[str, Any]:
    return {"title": [{"text": {"content": value}}]}


def _number(value: float) -> dict[str, Any]:
    return {"number": value}


def _select(value: str) -> dict[str, Any]:
    return {"select": {"name": value}}


def _date(dt: datetime | None = None) -> dict[str, Any]:
    iso = (dt or datetime.now(UTC)).isoformat()
    return {"date": {"start": iso}}


def _url(value: str) -> dict[str, Any]:
    return {"url": value}


# ---------------------------------------------------------------------------
# Property readers (from Notion API response)
# ---------------------------------------------------------------------------


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


def _read_url(page: dict[str, Any], prop: str) -> str:
    try:
        return page["properties"][prop]["url"] or ""
    except (KeyError, TypeError):
        return ""


def _page_url(page: dict[str, Any]) -> str:
    """Return the canonical Notion URL for a page."""
    page_id: str = page.get("id", "").replace("-", "")
    return f"https://www.notion.so/{page_id}"


# ---------------------------------------------------------------------------
# Signal Registry
# ---------------------------------------------------------------------------


async def get_approved_signals() -> list[dict[str, Any]]:
    """Query Signal Registry for approved signals in the last 48 hours.

    Filter: Board Decision = approved AND Agent != paper-trader
    Sorted by Score descending.
    """
    client = _get_client()
    cutoff = _48h_cutoff()

    response = await client.databases.query(
        database_id=SIGNAL_REGISTRY_DB,
        filter={
            "and": [
                {"property": "Board Decision", "select": {"equals": "approved"}},
                {"property": "Agent", "rich_text": {"does_not_equal": "paper-trader"}},
                {"property": "Date", "date": {"on_or_after": cutoff}},
            ]
        },
        sorts=[{"property": "Score", "direction": "descending"}],
    )

    results = response.get("results", [])
    logger.info("get_approved_signals: found %d approved signals", len(results))
    return [_parse_signal(p) for p in results]


def _48h_cutoff() -> str:
    from datetime import timedelta

    cutoff = datetime.now(UTC) - timedelta(hours=48)
    return cutoff.isoformat()


def _parse_signal(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page["id"],
        "url": _page_url(page),
        "ticker": _read_title(page, "Ticker") or _read_text(page, "Ticker"),
        "board_decision": _read_select(page, "Board Decision"),
        "agent": _read_text(page, "Agent"),
        "date": _read_date_start(page, "Date"),
        "score": _read_number(page, "Score"),
        "entry_price": _read_number(page, "Entry Price"),
        "stop": _read_number(page, "Stop"),
        "target": _read_number(page, "Target"),
        "direction": _read_select(page, "Direction") or "long",
        "thesis_id": _read_text(page, "Thesis ID"),
    }


async def mark_signal_executed(signal_id: str) -> None:
    """Transition Signal Registry Board Decision: approved → executed."""
    client = _get_client()
    await client.pages.update(
        page_id=signal_id,
        properties={"Board Decision": _select("executed")},
    )
    logger.debug("mark_signal_executed: %s", signal_id)


# ---------------------------------------------------------------------------
# Paper Portfolio DB
# ---------------------------------------------------------------------------


async def get_open_positions() -> list[dict[str, Any]]:
    """Query Paper Portfolio DB for all positions with Status = open."""
    client = _get_client()
    response = await client.databases.query(
        database_id=PAPER_PORTFOLIO_DB,
        filter={"property": "Status", "select": {"equals": "open"}},
    )
    results = response.get("results", [])
    logger.info("get_open_positions: found %d open positions", len(results))
    return [_parse_position(p) for p in results]


def _parse_position(page: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": page["id"],
        "url": _page_url(page),
        "ticker": _read_title(page, "Ticker"),
        "status": _read_select(page, "Status"),
        "entry_price": _read_number(page, "Entry Price"),
        "stop": _read_number(page, "Stop"),
        "target": _read_number(page, "Target"),
        "size": _read_number(page, "Size"),
        "direction": _read_select(page, "Direction") or "long",
        "entry_date": _read_date_start(page, "Entry Date"),
        "signal_id": _read_text(page, "Signal ID"),
        "thesis_id": _read_text(page, "Thesis ID"),
        "originating_agent": _read_text(page, "Originating Agent"),
    }


async def create_portfolio_position(
    *,
    ticker: str,
    entry_price: float,
    stop: float,
    target: float,
    size: float,
    direction: str,
    signal_id: str,
    thesis_id: str = "",
    risk_amount: float = 0.0,
    rr_ratio: float = 0.0,
) -> dict[str, Any]:
    """Create a new open position in the Paper Portfolio DB."""
    client = _get_client()
    now = datetime.now(UTC)
    page = await client.pages.create(
        parent={"database_id": PAPER_PORTFOLIO_DB},
        properties={
            "Ticker": _title(ticker),
            "Status": _select("open"),
            "Entry Price": _number(entry_price),
            "Stop": _number(stop),
            "Target": _number(target),
            "Size": _number(size),
            "Direction": _select(direction),
            "Entry Date": _date(now),
            "Signal ID": _text(signal_id),
            "Thesis ID": _text(thesis_id),
            "Originating Agent": _text("paper-trader"),
            "Unrealized PnL": _number(0.0),
            "Current Price": _number(entry_price),
        },
    )
    logger.info("create_portfolio_position: %s @ %.4f size=%.2f", ticker, entry_price, size)
    return {"id": page["id"], "url": _page_url(page)}


async def close_portfolio_position(
    *,
    position_id: str,
    exit_price: float,
    exit_reason: str,
    realized_pnl: float,
    r_multiple: float,
) -> None:
    """Close an open position: set Status=closed and write exit fields."""
    client = _get_client()
    outcome = "win" if r_multiple > 0 else "loss"
    await client.pages.update(
        page_id=position_id,
        properties={
            "Status": _select("closed"),
            "Exit Price": _number(exit_price),
            "Exit Date": _date(),
            "Exit Reason": _select(exit_reason),
            "Realized PnL": _number(realized_pnl),
            "R-Multiple": _number(r_multiple),
            "Outcome": _select(outcome),
        },
    )
    logger.info(
        "close_portfolio_position: %s r=%.2f outcome=%s", position_id, r_multiple, outcome
    )


# ---------------------------------------------------------------------------
# Trade Journal
# ---------------------------------------------------------------------------


async def create_trade_journal_open(
    *,
    ticker: str,
    signal_id: str,
    entry_price: float,
    stop: float,
    target: float,
    size: float,
    risk_amount: float,
    rr_ratio: float,
    direction: str,
    portfolio_page_url: str,
) -> dict[str, Any]:
    """Write a position-open entry to the Trade Journal."""
    client = _get_client()
    page = await client.pages.create(
        parent={"database_id": TRADE_JOURNAL_DB},
        properties={
            "Ticker": _title(ticker),
            "Event": _select("position-open"),
            "Signal ID": _text(signal_id),
            "Entry Price": _number(entry_price),
            "Stop": _number(stop),
            "Target": _number(target),
            "Size": _number(size),
            "Risk Amount": _number(risk_amount),
            "R-to-R Ratio": _number(rr_ratio),
            "Direction": _select(direction),
            "Open Date": _date(),
            "Portfolio Page": _url(portfolio_page_url),
        },
    )
    logger.debug("create_trade_journal_open: %s signal=%s", ticker, signal_id)
    return {"id": page["id"], "url": _page_url(page)}


async def create_trade_journal_close(
    *,
    ticker: str,
    signal_id: str,
    exit_price: float,
    exit_reason: str,
    realized_pnl: float,
    r_multiple: float,
    portfolio_page_url: str,
) -> dict[str, Any]:
    """Write a position-close entry to the Trade Journal."""
    client = _get_client()
    outcome = "win" if r_multiple > 0 else "loss"
    page = await client.pages.create(
        parent={"database_id": TRADE_JOURNAL_DB},
        properties={
            "Ticker": _title(ticker),
            "Event": _select("position-close"),
            "Signal ID": _text(signal_id),
            "Exit Price": _number(exit_price),
            "Exit Reason": _select(exit_reason),
            "Realized PnL": _number(realized_pnl),
            "R-Multiple": _number(r_multiple),
            "Outcome": _select(outcome),
            "Close Date": _date(),
            "Portfolio Page": _url(portfolio_page_url),
        },
    )
    logger.debug(
        "create_trade_journal_close: %s r=%.2f outcome=%s", ticker, r_multiple, outcome
    )
    return {"id": page["id"], "url": _page_url(page)}


# ---------------------------------------------------------------------------
# Execution Log
# ---------------------------------------------------------------------------


async def write_execution_log(
    *,
    run_id: str,
    status: str,
    errors: list[str] | None = None,
    output_page_url: str = "",
) -> None:
    """Mandatory per-run entry in the Execution Log DB.

    model is hard-coded to 'stonky-engine' (AC #6) to signal this is no longer
    a Claude-driven run.
    """
    client = _get_client()
    errors_text = "; ".join(errors) if errors else ""
    await client.pages.create(
        parent={"database_id": EXECUTION_LOG_DB},
        properties={
            "Run ID": _title(run_id),
            "Agent": _text("paper-trader"),
            "Timestamp": _date(datetime.now(UTC)),
            "Model": _text("stonky-engine"),
            "Status": _select(status),
            "Output Page URL": _url(output_page_url) if output_page_url else {"url": None},
            "Errors": _text(errors_text),
        },
    )
    logger.info("write_execution_log: run=%s status=%s", run_id, status)
