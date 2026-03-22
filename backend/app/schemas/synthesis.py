"""Pydantic schemas for the LLM synthesis API."""

from __future__ import annotations

from pydantic import BaseModel


class SynthesisResponse(BaseModel):
    """LLM synthesis result for a single symbol."""

    symbol: str
    generated_at: str
    setup_type: str
    bias: str
    confidence: str
    summary: str
    signal_confluence: str
    signal_conflicts: str
    entry: float | None = None
    stop: float | None = None
    target: float | None = None
    risk_reward: float | None = None
    key_risk: str
    parse_error: bool = False


class SynthesisScanRunResponse(BaseModel):
    """Response from triggering a synthesis scan."""

    run_id: int
    status: str
    symbols_queued: int


class SynthesisScanStatusResponse(BaseModel):
    """Status of a synthesis scan run."""

    run_id: int
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    symbols_scanned: int = 0
    symbols_synthesized: int = 0
