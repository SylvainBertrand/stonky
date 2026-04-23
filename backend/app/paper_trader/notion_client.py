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
    PORTFOLIO_STATE_DB,
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
    get_portfolio_state,
    mark_signal_executed,
    update_portfolio_state,
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
    """Write a paper-trader Execution Log entry (agent hardcoded to 'paper-trader').

    Paper Trader is a deterministic Stonky service (no LLM calls). Token fields
    are always written as 0 to distinguish these rows from unmeasured LLM rows.
    """
    await _write_execution_log(
        run_id=run_id,
        agent="paper-trader",
        model="stonky-engine",
        status=status,
        errors=errors,
        output_page_url=output_page_url,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        estimated_cost_usd=0.0,
    )


__all__ = [
    "EXECUTION_LOG_DB",
    "PAPER_PORTFOLIO_DB",
    "PORTFOLIO_STATE_DB",
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
    "get_portfolio_state",
    "mark_signal_executed",
    "update_portfolio_state",
    "write_execution_log",
]
