"""Discord webhook notifications for the Paper Trader service.

Sends Mobile Command Surface-standard embeds for:
  - position_open
  - position_close
  - run_summary
  - anomaly

Webhook URL is read from settings.discord_webhook_url. When the URL is not
configured the function logs a warning and returns silently.

Shared infrastructure (_post, _embed, colors) imported from agents_common.discord.

References:
  - Brief: briefs/paper-trader.yaml v1.0.0 (discord_notification schema)
  - Ticket: TC-007, TC-008 (agents_common extraction)
"""

from __future__ import annotations

import logging

from app.agents_common.discord import COLOR_GREEN, COLOR_RED, COLOR_YELLOW, _embed, _post

logger = logging.getLogger(__name__)


async def send_position_open(
    *,
    ticker: str,
    entry_price: float,
    stop: float,
    target: float,
    risk_amount: float,
    rr_ratio: float,
    notion_url: str,
    direction: str = "long",
) -> None:
    """Notify: new paper position opened."""
    direction_emoji = "\U0001f4c8" if direction == "long" else "\U0001f4c9"
    embed = _embed(
        title=f"{direction_emoji} Paper Trader \u2014 Position Opened: {ticker}",
        description=f"New {direction} position opened via stonky-engine.",
        color=COLOR_GREEN,
        fields=[
            {"name": "Entry", "value": f"${entry_price:,.2f}", "inline": True},
            {"name": "Stop", "value": f"${stop:,.2f}", "inline": True},
            {"name": "Target", "value": f"${target:,.2f}", "inline": True},
            {"name": "Risk", "value": f"${risk_amount:,.2f}", "inline": True},
            {"name": "R:R", "value": f"{rr_ratio:.2f}R", "inline": True},
            {"name": "Notion", "value": f"[Position]({notion_url})", "inline": True},
        ],
        url=notion_url,
    )
    await _post({"username": "Claude", "embeds": [embed]})


async def send_position_close(
    *,
    ticker: str,
    exit_price: float,
    exit_reason: str,
    realized_pnl: float,
    r_multiple: float,
    notion_url: str,
) -> None:
    """Notify: paper position closed."""
    win = r_multiple > 0
    emoji = "\u2705" if win else "\U0001f6d1"
    color = COLOR_GREEN if win else COLOR_RED
    embed = _embed(
        title=f"{emoji} Paper Trader \u2014 Position Closed: {ticker}",
        description=f"Exit reason: {exit_reason}.",
        color=color,
        fields=[
            {"name": "Exit Price", "value": f"${exit_price:,.2f}", "inline": True},
            {"name": "Realized PnL", "value": f"${realized_pnl:+,.2f}", "inline": True},
            {"name": "R-Multiple", "value": f"{r_multiple:+.2f}R", "inline": True},
            {"name": "Notion", "value": f"[Trade Journal]({notion_url})", "inline": True},
        ],
        url=notion_url,
    )
    await _post({"username": "Claude", "embeds": [embed]})


async def send_run_summary(
    *,
    run_id: str,
    positions_opened: int,
    positions_closed: int,
    status: str,
    notion_url: str = "",
) -> None:
    """Mandatory per-run summary — sent every run including silent ones."""
    if status == "success":
        color = COLOR_GREEN
        emoji = "\U0001f4ca"
    elif status == "partial":
        color = COLOR_YELLOW
        emoji = "\u26a0\ufe0f"
    else:
        color = COLOR_RED
        emoji = "\u274c"

    description = (
        f"Opened: **{positions_opened}** | Closed: **{positions_closed}** | Status: **{status}**"
    )
    embed = _embed(
        title=f"{emoji} Paper Trader \u2014 Run Summary",
        description=description,
        color=color,
        fields=[
            {"name": "Run ID", "value": run_id, "inline": False},
        ],
        url=notion_url,
    )
    await _post({"username": "Claude", "embeds": [embed]})


async def send_anomaly(*, description: str, notion_url: str = "") -> None:
    """Notify: unexpected condition requiring board attention."""
    embed = _embed(
        title="\u26a0\ufe0f Paper Trader \u2014 Anomaly Detected",
        description=description,
        color=COLOR_YELLOW,
        url=notion_url,
    )
    await _post({"username": "Claude", "embeds": [embed]})
