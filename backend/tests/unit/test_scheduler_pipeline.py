"""Tests for the parallelized scheduler pipeline orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.scheduler.pipeline import PipelineConfig, run_full_pipeline
from app.scheduler.progress import get_progress, reset_progress


@pytest.mark.unit
class TestPipelineConfig:
    def test_defaults(self):
        cfg = PipelineConfig()
        assert cfg.yolo_concurrency == 4
        assert cfg.chronos_concurrency == 4
        assert cfg.synthesis_concurrency == 1


@pytest.mark.unit
class TestProgressTracker:
    def test_reset_and_track(self):
        from app.scheduler.progress import (
            mark_pipeline_done,
            mark_symbol_done,
            mark_symbol_started,
        )

        reset_progress(10)
        p = get_progress()
        assert p.status == "running"
        assert p.total == 10
        assert p.completed == 0
        assert p.failed == 0

        mark_symbol_started("AAPL")
        assert "AAPL" in p.current_symbols

        mark_symbol_done("AAPL", success=True)
        assert p.completed == 1
        assert "AAPL" not in p.current_symbols

        mark_symbol_done("BAD", success=False)
        assert p.failed == 1

        mark_pipeline_done(success=True)
        assert p.status == "completed"
        assert p.completed_at is not None

    def test_estimated_remaining_none_when_no_completions(self):
        reset_progress(10)
        p = get_progress()
        assert p.estimated_remaining_s is None


@pytest.mark.unit
class TestRunFullPipeline:
    """Test pipeline orchestration with mocked job functions."""

    @pytest.mark.asyncio
    async def test_all_symbols_attempted(self):
        """All symbols should be attempted even if some fail."""
        call_log: list[str] = []

        async def mock_pipeline(
            symbol_id, ticker, scan_run_id, outer_sem, chronos_sem, ollama_sem, sf
        ):
            call_log.append(ticker)
            from app.scheduler.progress import mark_symbol_done, mark_symbol_started

            async with outer_sem:
                mark_symbol_started(ticker)
                if ticker == "BAD":
                    mark_symbol_done(ticker, success=False)
                    raise RuntimeError("Intentional failure")
                mark_symbol_done(ticker, success=True)

        symbols = [(1, "AAPL"), (2, "BAD"), (3, "NVDA")]
        config = PipelineConfig(yolo_concurrency=4, chronos_concurrency=4, synthesis_concurrency=1)
        mock_factory = MagicMock()

        with patch(
            "app.scheduler.pipeline._run_symbol_pipeline",
            side_effect=mock_pipeline,
        ):
            result = await run_full_pipeline(symbols, config, mock_factory, scan_run_id=1)

        assert len(call_log) == 3
        assert set(call_log) == {"AAPL", "BAD", "NVDA"}
        assert result["completed"] == 2
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_concurrency_bounded(self):
        """No more than yolo_concurrency symbols should run simultaneously."""
        max_concurrent = 0
        current_concurrent = 0
        lock = asyncio.Lock()

        async def mock_pipeline(
            symbol_id, ticker, scan_run_id, outer_sem, chronos_sem, ollama_sem, sf
        ):
            nonlocal max_concurrent, current_concurrent
            from app.scheduler.progress import mark_symbol_done, mark_symbol_started

            async with outer_sem:
                mark_symbol_started(ticker)
                async with lock:
                    current_concurrent += 1
                    if current_concurrent > max_concurrent:
                        max_concurrent = current_concurrent

                await asyncio.sleep(0.05)

                async with lock:
                    current_concurrent -= 1

                mark_symbol_done(ticker, success=True)

        symbols = [(i, f"SYM{i}") for i in range(10)]
        config = PipelineConfig(yolo_concurrency=2, chronos_concurrency=4, synthesis_concurrency=1)
        mock_factory = MagicMock()

        with patch(
            "app.scheduler.pipeline._run_symbol_pipeline",
            side_effect=mock_pipeline,
        ):
            result = await run_full_pipeline(symbols, config, mock_factory, scan_run_id=1)

        assert max_concurrent <= 2
        assert result["completed"] == 10

    @pytest.mark.asyncio
    async def test_session_factory_called_per_symbol(self):
        """Each symbol pipeline should get its own DB session."""
        session_count = 0

        class FakeSession:
            async def __aenter__(self):
                nonlocal session_count
                session_count += 1
                return AsyncMock()

            async def __aexit__(self, *args):
                pass

        def fake_factory():
            return FakeSession()

        symbols = [(1, "AAPL"), (2, "NVDA"), (3, "MSFT")]
        config = PipelineConfig(yolo_concurrency=4, chronos_concurrency=4, synthesis_concurrency=1)

        with (
            patch("app.scheduler.pipeline._run_yolo_for_symbol", new_callable=AsyncMock),
            patch("app.scheduler.pipeline._run_chronos_for_symbol", new_callable=AsyncMock),
            patch("app.scheduler.pipeline._run_synthesis_for_symbol", new_callable=AsyncMock),
        ):
            result = await run_full_pipeline(symbols, config, fake_factory, scan_run_id=1)

        assert session_count == 3
        assert result["completed"] == 3

    @pytest.mark.asyncio
    async def test_ollama_semaphore_serializes(self):
        """The Ollama semaphore should prevent more than 1 concurrent synthesis call."""
        max_synthesis_concurrent = 0
        current_synthesis = 0
        synthesis_lock = asyncio.Lock()

        async def mock_synthesis(symbol_id, ticker, db, semaphore):
            nonlocal max_synthesis_concurrent, current_synthesis
            async with semaphore:
                async with synthesis_lock:
                    current_synthesis += 1
                    if current_synthesis > max_synthesis_concurrent:
                        max_synthesis_concurrent = current_synthesis
                await asyncio.sleep(0.02)
                async with synthesis_lock:
                    current_synthesis -= 1

        class FakeSession:
            async def __aenter__(self):
                return AsyncMock()

            async def __aexit__(self, *args):
                pass

        def fake_factory():
            return FakeSession()

        symbols = [(i, f"SYM{i}") for i in range(5)]
        config = PipelineConfig(yolo_concurrency=5, chronos_concurrency=5, synthesis_concurrency=1)

        with (
            patch("app.scheduler.pipeline._run_yolo_for_symbol", new_callable=AsyncMock),
            patch("app.scheduler.pipeline._run_chronos_for_symbol", new_callable=AsyncMock),
            patch(
                "app.scheduler.pipeline._run_synthesis_for_symbol",
                side_effect=mock_synthesis,
            ),
        ):
            result = await run_full_pipeline(symbols, config, fake_factory, scan_run_id=1)

        assert max_synthesis_concurrent <= 1
        assert result["completed"] == 5

    @pytest.mark.asyncio
    async def test_empty_symbols_list(self):
        """Pipeline with no symbols should complete immediately."""
        config = PipelineConfig()
        mock_factory = MagicMock()
        result = await run_full_pipeline([], config, mock_factory, scan_run_id=1)
        assert result["completed"] == 0
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_failure_isolation_per_step(self):
        """YOLO failure for one symbol should not prevent Chronos/Synthesis for that symbol."""
        yolo_calls: list[str] = []
        chronos_calls: list[str] = []
        synthesis_calls: list[str] = []

        async def mock_yolo(symbol_id, ticker, scan_run_id, db):
            yolo_calls.append(ticker)
            if ticker == "FAIL":
                raise RuntimeError("YOLO boom")

        async def mock_chronos(symbol_id, ticker, db, semaphore):
            chronos_calls.append(ticker)

        async def mock_synthesis(symbol_id, ticker, db, semaphore):
            synthesis_calls.append(ticker)

        class FakeSession:
            async def __aenter__(self):
                mock = AsyncMock()
                mock.rollback = AsyncMock()
                return mock

            async def __aexit__(self, *args):
                pass

        def fake_factory():
            return FakeSession()

        symbols = [(1, "AAPL"), (2, "FAIL"), (3, "NVDA")]
        config = PipelineConfig(yolo_concurrency=4, chronos_concurrency=4, synthesis_concurrency=1)

        with (
            patch("app.scheduler.pipeline._run_yolo_for_symbol", side_effect=mock_yolo),
            patch(
                "app.scheduler.pipeline._run_chronos_for_symbol",
                side_effect=mock_chronos,
            ),
            patch(
                "app.scheduler.pipeline._run_synthesis_for_symbol",
                side_effect=mock_synthesis,
            ),
        ):
            result = await run_full_pipeline(symbols, config, fake_factory, scan_run_id=1)

        # All symbols attempted for all steps (YOLO failure is caught per-step)
        assert len(yolo_calls) == 3
        assert len(chronos_calls) == 3  # FAIL still gets Chronos
        assert len(synthesis_calls) == 3  # FAIL still gets synthesis
        assert result["completed"] == 3
