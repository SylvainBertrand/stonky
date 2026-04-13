"""Notion API client for the Paper Trader service.

Thin re-export of agents_common.notion_client, which holds the shared
implementation used by both paper_trader and portfolio_monitor (TC-008).

The write_execution_log wrapper below passes agent="paper-trader" so
callers that don't supply the agent parameter continue to work.

References:
  - Brief: briefs/paper-trader.yaml v1.0.0
  - Ticket: TC-008 (agents_common extraction)
"""

from __future__ import annotations

# Re-export everything from agents_common for backward compatibility
from app.agents_common.notion_client import (
    EXECUTION_LOG_DB,
    PAPER_PORTFOLIO_DB,
    SIGNAL_REGISTRY_DB,
    TRADE_JOURNAL_DB,
    _create_page,
    _date,
    _get_client,
    _number,
    _page_url,
    _parse_position,
    _parse_signal,
    _query_database,
    _read_date_start,
    _read_number,
    _read_select,
    _read_text,
    _read_title,
    _select,
    _text,
    _title,
    _update_page,
    _url,
    close_portfolio_position,
    create_portfolio_position,
    create_trade_journal_close,
    create_trade_journal_open,
    get_approved_signals,
    get_open_positions,
    mark_signal_executed,
)
from app.agents_common.notion_client import (
    write_execution_log as _write_execution_log,
)


async def write_execution_log(
    *,
    run_id: str,
    status: str,
    errors: list[str] | None = None,
    output_page_url: str = "",
) -> None:
    """Write a paper-trader Execution Log entry (agent hardcoded to 'paper-trader')."""
    await _write_execution_log(
        run_id=run_id,
        agent="paper-trader",
        model="stonky-engine",
        status=status,
        errors=errors,
        output_page_url=output_page_url,
    )


__all__ = [
    "EXECUTION_LOG_DB",
    "PAPER_PORTFOLIO_DB",
    "SIGNAL_REGISTRY_DB",
    "TRADE_JOURNAL_DB",
    "_create_page",
    "_date",
    "_get_client",
    "_number",
    "_page_url",
    "_parse_position",
    "_parse_signal",
    "_query_database",
    "_read_date_start",
    "_read_number",
    "_read_select",
    "_read_text",
    "_read_title",
    "_select",
    "_text",
    "_title",
    "_update_page",
    "_url",
    "close_portfolio_position",
    "create_portfolio_position",
    "create_trade_journal_close",
    "create_trade_journal_open",
    "get_approved_signals",
    "get_open_positions",
    "mark_signal_executed",
    "write_execution_log",
]
