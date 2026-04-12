"""Paper Trader — deterministic Stonky backend service.

Replaces the Claude Code workflow 04 (Paper Trader). All logic is fixed rules
with zero LLM judgment: R:R validation, position sizing, stop/target comparison,
PnL math. Runs as an APScheduler job inside the existing stonky-backend service.
"""
