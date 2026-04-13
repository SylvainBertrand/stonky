"""Shared Discord webhook infrastructure for Stonky autonomous agents.

Provides:
  - Color constants (Trading Company palette)
  - _post() — raw payload sender
  - _embed() — embed builder
  - send_critical_alert() — generic critical alert (STOP_BREACH, TARGET_BREACH, ANDON_CORD)

Agent-specific message functions live in their own modules:
  - paper_trader/discord.py (position_open, position_close, run_summary)
  - portfolio_monitor/report.py (per-run Discord summary for portfolio monitor)

References:
  - Brief: briefs/paper-trader.yaml v1.0.0
  - Brief: briefs/portfolio-monitor.yaml v2.0.0
  - Ticket: TC-008
"""

from __future__ import annotations

import logging

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Trading Company color palette (AC #5)
COLOR_GREEN = 3_066_993  # clean success
COLOR_YELLOW = 16_776_960  # partial / informational
COLOR_RED = 15_158_332  # failure / loss / critical


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


async def send_critical_alert(
    *,
    flag_type: str,
    ticker: str,
    current_price: float,
    description: str,
    report_url: str = "",
) -> None:
    """Send an immediate critical Discord alert.

    Used for: STOP_BREACH, TARGET_BREACH, ANDON_CORD.
    One alert per event — do not batch (brief guardrail).
    """
    embed = _embed(
        title=f"\U0001f6a8 Portfolio Monitor \u2014 {flag_type}",
        description=(f"**{ticker}** @ ${current_price:,.2f}\n{description}"),
        color=COLOR_RED,
        fields=(
            [{"name": "\U0001f4cb Review", "value": f"[Report]({report_url})", "inline": False}]
            if report_url
            else None
        ),
        url=report_url,
    )
    await _post({"username": "Claude", "embeds": [embed]})
