"""Discord webhook notifications for the Paper Trader service.

Sends Mobile Command Surface-standard embeds for:
  - position_open
  - position_close
  - run_summary
  - anomaly

Webhook URL is read from settings.discord_webhook_url. When the URL is not
configured the function logs a warning and returns silently — callers should
not treat a missing webhook as a fatal error, but a missing per-run summary
IS treated as a failure by the brief guardrails (callers enforce this).

References:
  - Brief: briefs/paper-trader.yaml v1.0.0 (discord_notification schema)
  - Ticket: TC-007 Acceptance Criteria #5
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Trading Company color palette (AC #5)
COLOR_GREEN = 3_066_993  # clean success
COLOR_YELLOW = 16_776_960  # partial / informational
COLOR_RED = 15_158_332  # failure / loss


async def _post(payload: dict[str, object]) -> None:
    """POST a Discord embed payload to the configured webhook."""
    url = settings.discord_webhook_url
    if not url:
        logger.warning("discord_webhook_url not configured — skipping Discord notification")
        return

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code not in (200, 204):
            logger.error("Discord webhook returned %s: %s", resp.status_code, resp.text[:200])


def _embed(
    *,
    title: str,
    description: str,
    color: int,
    fields: list[dict[str, object]] | None = None,
    url: str = "",
) -> dict[str, object]:
    embed: dict[str, object] = {"title": title, "description": description, "color": color}
    if fields:
        embed["fields"] = fields
    if url:
        embed["url"] = url
    return embed


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
    direction_emoji = "📈" if direction == "long" else "📉"
    embed = _embed(
        title=f"{direction_emoji} Paper Trader — Position Opened: {ticker}",
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
    emoji = "✅" if win else "🛑"
    color = COLOR_GREEN if win else COLOR_RED
    embed = _embed(
        title=f"{emoji} Paper Trader — Position Closed: {ticker}",
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
        emoji = "📊"
    elif status == "partial":
        color = COLOR_YELLOW
        emoji = "⚠️"
    else:
        color = COLOR_RED
        emoji = "❌"

    description = (
        f"Opened: **{positions_opened}** | Closed: **{positions_closed}** | Status: **{status}**"
    )
    embed = _embed(
        title=f"{emoji} Paper Trader — Run Summary",
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
        title="⚠️ Paper Trader — Anomaly Detected",
        description=description,
        color=COLOR_YELLOW,
        url=notion_url,
    )
    await _post({"username": "Claude", "embeds": [embed]})
