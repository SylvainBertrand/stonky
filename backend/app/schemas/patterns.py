"""Pydantic schemas for the chart patterns API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class PatternDetectionResponse(BaseModel):
    """Single YOLOv8 pattern detection."""

    pattern: str
    direction: str
    confidence: float
    bar_start: int
    bar_end: int


class SymbolPatternsResponse(BaseModel):
    """YOLOv8 pattern detections for a symbol."""

    symbol: str
    scanned_at: datetime | None = None
    detections: list[PatternDetectionResponse]


class PatternScanRunResponse(BaseModel):
    """Response from triggering a YOLO pattern scan."""

    run_id: int
    status: str
    symbols_queued: int


class PatternScanStatusResponse(BaseModel):
    """Status of a YOLO pattern scan run."""

    run_id: int
    status: str
    started_at: str | None = None
    completed_at: str | None = None
    symbols_scanned: int = 0
    total_detections: int = 0
