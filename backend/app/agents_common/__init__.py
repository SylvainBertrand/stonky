"""Shared infrastructure for Stonky autonomous agents.

Provides:
  - notion_client  — reads/writes to Notion databases (Signal Registry,
                     Paper Portfolio, Execution Log, Signal Anomalies)
  - discord        — webhook helpers, embed builders, color constants
  - scheduler      — NYSE-hours gating utility

Consumed by: paper_trader, portfolio_monitor.
"""
