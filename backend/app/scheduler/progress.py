"""In-memory pipeline progress tracker.

Provides a singleton ``PipelineProgress`` that the pipeline orchestrator
updates as symbols complete.  The ``/api/pipeline/status`` endpoint reads
this to show live progress in the UI.

State resets on server restart — no DB needed.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class PipelineProgress:
    status: str = "idle"  # idle | running | completed | failed
    started_at: datetime | None = None
    completed_at: datetime | None = None
    total: int = 0
    completed: int = 0
    failed: int = 0
    current_symbols: list[str] = field(default_factory=list)

    @property
    def estimated_remaining_s(self) -> float | None:
        if self.status != "running" or self.completed == 0 or self.started_at is None:
            return None
        elapsed = time.time() - self.started_at.timestamp()
        per_symbol = elapsed / self.completed
        remaining = self.total - self.completed - self.failed
        return round(per_symbol * remaining, 1)


_progress = PipelineProgress()


def get_progress() -> PipelineProgress:
    return _progress


def reset_progress(total: int) -> None:
    _progress.status = "running"
    _progress.started_at = datetime.now(UTC)
    _progress.completed_at = None
    _progress.total = total
    _progress.completed = 0
    _progress.failed = 0
    _progress.current_symbols = []


def mark_symbol_started(symbol: str) -> None:
    if symbol not in _progress.current_symbols:
        _progress.current_symbols.append(symbol)


def mark_symbol_done(symbol: str, *, success: bool = True) -> None:
    if success:
        _progress.completed += 1
    else:
        _progress.failed += 1
    if symbol in _progress.current_symbols:
        _progress.current_symbols.remove(symbol)


def mark_pipeline_done(*, success: bool = True) -> None:
    _progress.status = "completed" if success else "failed"
    _progress.completed_at = datetime.now(UTC)
    _progress.current_symbols = []
