"""Portfolio Monitor — Notion report page builder and Discord summary.

Builds the per-run Notion report page under Agent Output / Portfolio Monitor
and sends the per-run Discord summary embed.

The Notion report destination is:
  Agent Output > Portfolio Monitor > {run_date}

Every run creates a page even when no flags are found (brief guardrail).

References:
  - Brief: briefs/portfolio-monitor.yaml v2.0.0 (output section)
  - Ticket: TC-008 Acceptance Criteria #2, #5
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.agents_common.discord import COLOR_GREEN, COLOR_RED, COLOR_YELLOW, _embed, _post
from app.agents_common.notion_client import _get_client
from app.config import settings
from app.portfolio_monitor.engine import Flag, Severity

logger = logging.getLogger(__name__)

# Notion page ID for "Agent Output > Portfolio Monitor" parent
# This will be the parent page under which per-run report pages are created.
# Set to the actual page ID once known; falls back to creating under workspace root.
PORTFOLIO_MONITOR_PARENT_PAGE_ID = ""  # set via env var PORTFOLIO_MONITOR_PARENT_ID


def _get_parent_page_id() -> str | None:
    """Return the Notion parent page ID from settings or env, if configured."""
    return (
        getattr(settings, "portfolio_monitor_parent_page_id", None)
        or PORTFOLIO_MONITOR_PARENT_PAGE_ID
        or None
    )


async def create_run_report(
    *,
    run_id: str,
    run_timestamp: datetime,
    positions_evaluated: int,
    flags: list[Flag],
    andon_triggered: bool,
    andon_reason: str,
    errors: list[str],
) -> str:
    """Create a Notion report page for this run. Returns the page URL.

    Page is created even when zero flags are found (brief guardrail).
    """
    client = _get_client()

    title = f"Portfolio Monitor — {run_timestamp.strftime('%Y-%m-%d %H:%M')} UTC"

    # Group flags by type for the report
    by_type: dict[str, list[Flag]] = {}
    for flag in flags:
        key = flag.flag_type.value
        by_type.setdefault(key, []).append(flag)

    # Build page content as Notion blocks
    blocks: list[dict[str, Any]] = []

    # Summary heading
    flag_count = len(flags)
    critical_count = sum(1 for f in flags if f.severity == Severity.CRITICAL)
    status_text = "CRITICAL" if critical_count > 0 else ("WARNINGS" if flag_count > 0 else "CLEAN")
    blocks.append(
        _paragraph(
            f"Run ID: {run_id} | Positions evaluated: {positions_evaluated} | "
            f"Flags: {flag_count} ({critical_count} critical) | Status: {status_text}"
        )
    )

    if andon_triggered:
        blocks.append(_paragraph(f"ANDON CORD TRIGGERED: {andon_reason}"))

    if errors:
        blocks.append(_paragraph(f"Errors: {'; '.join(errors)}"))

    # Per-check sections
    check_names = [
        ("STOP_PROXIMITY", "CHECK-01: Stop Proximity"),
        ("TARGET_PROXIMITY", "CHECK-02: Target Proximity"),
        ("STOP_BREACH", "CHECK-03: Stop Breach"),
        ("TARGET_BREACH", "CHECK-03: Target Breach"),
        ("CONCENTRATION_RISK", "CHECK-04: Concentration Risk"),
        ("CORRELATION_RISK", "CHECK-05: Correlation Risk"),
        ("STALE", "CHECK-07: Stale Positions"),
        ("DATA_MISSING", "Data Missing (Critical)"),
    ]
    for flag_type_key, section_title in check_names:
        section_flags = by_type.get(flag_type_key, [])
        blocks.append(_heading3(section_title))
        if section_flags:
            for f in section_flags:
                blocks.append(_bullet(f.description))
        else:
            blocks.append(_bullet("Clean — no flags."))

    # Build the page
    parent_page_id = _get_parent_page_id()
    parent: dict[str, Any] = (
        {"page_id": parent_page_id} if parent_page_id else {"type": "workspace", "workspace": True}
    )

    try:
        page: dict[str, Any] = await client.request(
            path="pages",
            method="POST",
            body={
                "parent": parent,
                "properties": {
                    "title": {"title": [{"text": {"content": title}}]},
                },
                "children": blocks,
            },
        )
        page_id = page.get("id", "").replace("-", "")
        page_url = f"https://www.notion.so/{page_id}"
        logger.info("create_run_report: created page %s", page_url)
        return page_url
    except Exception as exc:
        logger.error("create_run_report: failed to create Notion page: %s", exc)
        return ""


def _paragraph(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _heading3(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "heading_3",
        "heading_3": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


def _bullet(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "bulleted_list_item",
        "bulleted_list_item": {"rich_text": [{"type": "text", "text": {"content": text}}]},
    }


# ---------------------------------------------------------------------------
# Discord summary sender
# ---------------------------------------------------------------------------


async def send_run_summary(
    *,
    run_id: str,
    run_timestamp: datetime,
    positions_evaluated: int,
    flags: list[Flag],
    status: str,
    report_url: str = "",
) -> None:
    """Send the mandatory per-run Discord summary.

    Format (from brief):
      🔍 Portfolio Monitor — {YYYY-MM-DD HH:MM}
      {N} open positions | {M} flags | Status: {clean/warnings/critical}
      {If flags: list top 3}
      📋 Report: ...
    """
    flag_count = len(flags)
    critical_count = sum(1 for f in flags if f.severity == Severity.CRITICAL)
    status_label = "critical" if critical_count > 0 else ("warnings" if flag_count > 0 else "clean")

    if status == "success":
        color = COLOR_GREEN if status_label == "clean" else COLOR_YELLOW
    elif status == "partial":
        color = COLOR_YELLOW
    else:
        color = COLOR_RED

    emoji = "\U0001f50d"  # 🔍
    ts_str = run_timestamp.strftime("%Y-%m-%d %H:%M")
    description = (
        f"{positions_evaluated} open positions | {flag_count} flags | Status: **{status_label}**"
    )

    fields: list[dict[str, object]] = []
    # Top 3 flags
    critical_first = sorted(flags, key=lambda f: 0 if f.severity == Severity.CRITICAL else 1)
    for f in critical_first[:3]:
        fields.append(
            {
                "name": f.flag_type.value,
                "value": f.description[:200],
                "inline": False,
            }
        )

    if report_url:
        fields.append(
            {
                "name": "\U0001f4cb Report",
                "value": f"[Notion]({report_url})",
                "inline": False,
            }
        )

    embed = _embed(
        title=f"{emoji} Portfolio Monitor \u2014 {ts_str}",
        description=description,
        color=color,
        fields=fields if fields else None,
        url=report_url,
    )
    await _post({"username": "Claude", "embeds": [embed]})
