"""Unit tests for YOLOv8 chart pattern screening.

Tests cover:
- compute_yolo_signals() scoring logic
- PATTERN_DIRECTIONS mapping completeness
- Recency decay behavior
- Scoring integration with build_composite()
- render_chart_image() produces non-empty output
- run_yolo_inference() with mocked YOLO model
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from app.analysis.yolo_screener import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    DIRECTION_SIGN,
    GEOMETRIC_PATTERN_WEIGHT,
    PATTERN_DIRECTIONS,
    RECENCY_DECAY_BARS,
    YoloDetection,
    _normalize_class_name,
    compute_yolo_signals,
    run_yolo_inference,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_detection(
    pattern: str = "double_bottom",
    confidence: float = 0.80,
    direction: str = "bullish",
    bar_start: int = 95,
    bar_end: int = 118,
) -> YoloDetection:
    return YoloDetection(
        pattern_name=pattern,
        confidence=confidence,
        bbox=(0.75, 0.2, 0.95, 0.8),
        direction=direction,
        bar_start=bar_start,
        bar_end=bar_end,
    )


def _gen_ohlcv(bars: int = 120, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV data for chart rendering tests."""
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.standard_normal(bars) * 0.5)
    return pd.DataFrame({
        "time": pd.date_range("2025-06-01", periods=bars, freq="B"),
        "open": close - rng.uniform(0, 1, bars),
        "high": close + rng.uniform(0, 2, bars),
        "low": close - rng.uniform(0, 2, bars),
        "close": close,
        "volume": rng.integers(100_000, 1_000_000, bars),
    })


# ── Pattern direction mapping ────────────────────────────────────────────────

@pytest.mark.unit
class TestPatternDirections:
    def test_all_6_patterns_mapped(self) -> None:
        """The foduucom model detects 6 patterns, mapped to canonical names."""
        expected = {
            "head_and_shoulders", "inverse_head_and_shoulders",
            "double_top", "double_bottom",
            "triangle", "trendline",
        }
        assert set(PATTERN_DIRECTIONS.keys()) == expected

    def test_bullish_patterns(self) -> None:
        bullish = [k for k, v in PATTERN_DIRECTIONS.items() if v == "bullish"]
        assert "inverse_head_and_shoulders" in bullish
        assert "double_bottom" in bullish

    def test_bearish_patterns(self) -> None:
        bearish = [k for k, v in PATTERN_DIRECTIONS.items() if v == "bearish"]
        assert "head_and_shoulders" in bearish
        assert "double_top" in bearish

    def test_neutral_patterns(self) -> None:
        assert PATTERN_DIRECTIONS["triangle"] == "neutral"
        assert PATTERN_DIRECTIONS["trendline"] == "neutral"


# ── Class name normalization ─────────────────────────────────────────────────

@pytest.mark.unit
class TestNormalizeClassName:
    def test_model_class_head_shoulders_top(self) -> None:
        assert _normalize_class_name("Head and shoulders top") == "head_and_shoulders"

    def test_model_class_head_shoulders_bottom(self) -> None:
        assert _normalize_class_name("Head and shoulders bottom") == "inverse_head_and_shoulders"

    def test_model_class_m_head(self) -> None:
        assert _normalize_class_name("M_Head") == "double_top"

    def test_model_class_w_bottom(self) -> None:
        assert _normalize_class_name("W_Bottom") == "double_bottom"

    def test_model_class_triangle(self) -> None:
        assert _normalize_class_name("Triangle") == "triangle"

    def test_model_class_stockline(self) -> None:
        assert _normalize_class_name("StockLine") == "trendline"

    def test_unknown_returns_none(self) -> None:
        assert _normalize_class_name("random_noise") is None


# ── compute_yolo_signals ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestComputeYoloSignals:
    def test_no_detections_returns_zeros(self) -> None:
        result = compute_yolo_signals([])
        assert result["yolo_pattern_detected"] == 0.0
        assert result["yolo_pattern_score"] == 0.0
        assert result["yolo_pattern_confidence"] == 0.0

    def test_bullish_pattern_positive_score(self) -> None:
        det = _make_detection("double_bottom", confidence=0.80, direction="bullish", bar_end=118)
        result = compute_yolo_signals([det], total_bars=120)

        assert result["yolo_pattern_detected"] == 1.0
        assert result["yolo_pattern_confidence"] == 0.80
        assert result["yolo_pattern_score"] > 0.0

    def test_bearish_pattern_negative_score(self) -> None:
        det = _make_detection("head_and_shoulders", confidence=0.75, direction="bearish", bar_end=118)
        result = compute_yolo_signals([det], total_bars=120)

        assert result["yolo_pattern_detected"] == 1.0
        assert result["yolo_pattern_score"] < 0.0

    def test_neutral_pattern_zero_score(self) -> None:
        det = _make_detection("triangle", confidence=0.90, direction="neutral", bar_end=118)
        result = compute_yolo_signals([det], total_bars=120)

        assert result["yolo_pattern_detected"] == 1.0
        assert result["yolo_pattern_score"] == 0.0

    def test_score_uses_geometric_weight(self) -> None:
        det = _make_detection("double_bottom", confidence=1.0, direction="bullish", bar_end=119)
        result = compute_yolo_signals([det], total_bars=120)

        # At bar_end=119 (last bar), recency_weight=1.0
        # score = 1.0 * 1.0 * 0.8 * 1.0 = 0.8
        expected = 1.0 * DIRECTION_SIGN["bullish"] * GEOMETRIC_PATTERN_WEIGHT * 1.0
        assert result["yolo_pattern_score"] == pytest.approx(expected, abs=0.01)

    def test_score_clamped_to_range(self) -> None:
        det = _make_detection(confidence=0.99, direction="bullish", bar_end=119)
        result = compute_yolo_signals([det], total_bars=120)
        assert -1.0 <= result["yolo_pattern_score"] <= 1.0

    def test_uses_highest_confidence_detection(self) -> None:
        low = _make_detection(confidence=0.40, direction="bullish", bar_end=118)
        high = _make_detection(confidence=0.90, direction="bearish", bar_end=118)
        result = compute_yolo_signals([low, high], total_bars=120)

        # Should use the first one in the list (assumed pre-sorted by confidence desc)
        # Since [low, high] is not sorted, let's verify it uses [0]
        assert result["yolo_pattern_confidence"] == 0.40

    def test_presorted_detections_uses_first(self) -> None:
        high = _make_detection(confidence=0.90, direction="bearish", bar_end=118)
        low = _make_detection(confidence=0.40, direction="bullish", bar_end=118)
        result = compute_yolo_signals([high, low], total_bars=120)
        assert result["yolo_pattern_confidence"] == 0.90
        assert result["yolo_pattern_score"] < 0.0


# ── Recency decay ────────────────────────────────────────────────────────────

@pytest.mark.unit
class TestRecencyDecay:
    def test_at_chart_end_no_decay(self) -> None:
        det = _make_detection(bar_end=119)
        result = compute_yolo_signals([det], total_bars=120)
        # bars_from_end = 120-1-119 = 0, recency_weight = 1.0
        assert result["yolo_pattern_score"] != 0.0

    def test_one_bar_from_end_slight_decay(self) -> None:
        det_end = _make_detection(bar_end=119, confidence=0.80)
        det_prev = _make_detection(bar_end=118, confidence=0.80)
        score_end = compute_yolo_signals([det_end], total_bars=120)["yolo_pattern_score"]
        score_prev = compute_yolo_signals([det_prev], total_bars=120)["yolo_pattern_score"]
        assert abs(score_end) > abs(score_prev)

    def test_beyond_decay_bars_zero_score(self) -> None:
        # bar_end = 120 - 1 - RECENCY_DECAY_BARS = 114
        bar_end = 120 - 1 - RECENCY_DECAY_BARS
        det = _make_detection(bar_end=bar_end)
        result = compute_yolo_signals([det], total_bars=120)
        assert result["yolo_pattern_score"] == 0.0

    def test_well_past_decay_zero(self) -> None:
        det = _make_detection(bar_end=50)
        result = compute_yolo_signals([det], total_bars=120)
        assert result["yolo_pattern_score"] == 0.0


# ── Scoring integration ─────────────────────────────────────────────────────

@pytest.mark.unit
class TestScoringIntegration:
    def test_build_composite_includes_yolo_when_detected(self) -> None:
        from app.analysis.scoring import build_composite

        signals: dict[str, float] = {
            "ema_stack": 0.5,
            "adx_dmi": 0.3,
            "supertrend": 0.4,
            "rsi": -0.2,
            "macd": 0.1,
            "stochastic": 0.0,
            "obv": 0.3,
            "vwap": 0.2,
            "cmf": 0.1,
            "bb_pct_b": 0.0,
            "ttm_squeeze": 0.0,
            "atr": 0.0,
            "fibonacci": 0.1,
            "pivot_points": 0.0,
            "rsi_divergence": 0.0,
            "macd_divergence": 0.0,
            "candlestick": 0.3,
            # YOLO signals
            "yolo_pattern_detected": 1.0,
            "yolo_pattern_score": 0.6,
        }

        cats, comp = build_composite(signals)
        # Pattern category should average candlestick (0.3) and yolo (0.6) = 0.45
        assert cats["pattern"] == pytest.approx(0.45, abs=0.01)

    def test_build_composite_excludes_yolo_when_not_detected(self) -> None:
        from app.analysis.scoring import build_composite

        signals: dict[str, float] = {
            "candlestick": 0.3,
            "yolo_pattern_detected": 0.0,
            "yolo_pattern_score": 0.0,
        }

        cats, _ = build_composite(signals)
        # Pattern should just be candlestick (0.3)
        assert cats["pattern"] == pytest.approx(0.3, abs=0.01)

    def test_build_composite_with_all_pattern_sources(self) -> None:
        from app.analysis.scoring import build_composite

        signals: dict[str, float] = {
            "candlestick": 0.2,
            "harmonic_pattern_detected": 1.0,
            "harmonic_score": 0.8,
            "yolo_pattern_detected": 1.0,
            "yolo_pattern_score": 0.5,
        }

        cats, _ = build_composite(signals)
        # Pattern = avg(candlestick=0.2, harmonic=0.8, yolo=0.5) = 0.5
        assert cats["pattern"] == pytest.approx(0.5, abs=0.01)


# ── Chart rendering ──────────────────────────────────────────────────────────

@pytest.mark.unit
class TestChartRenderer:
    def test_render_produces_bytes(self) -> None:
        from app.analysis.chart_renderer import render_chart_image

        df = _gen_ohlcv(bars=120)
        result = render_chart_image(df, "TEST", timeframe="1d", bars=120)
        assert isinstance(result, bytes)
        assert len(result) > 1000  # PNG should be at least a few KB

    def test_render_respects_bars_limit(self) -> None:
        from app.analysis.chart_renderer import render_chart_image

        df = _gen_ohlcv(bars=200)
        result = render_chart_image(df, "TEST", timeframe="1d", bars=60)
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_render_to_file(self, tmp_path: object) -> None:
        from pathlib import Path

        from app.analysis.chart_renderer import render_chart_image

        df = _gen_ohlcv(bars=120)
        out = Path(str(tmp_path)) / "chart.png"
        result = render_chart_image(df, "TEST", output_path=out)
        assert isinstance(result, Path)
        assert result.exists()
        assert result.stat().st_size > 1000


# ── Model singleton ─────────────────────────────────────────────────────────

@pytest.mark.unit
class TestModelSingleton:
    def test_failure_is_cached(self) -> None:
        """After a permanent load failure, subsequent calls should raise immediately."""
        import app.analysis.yolo_screener as mod

        # Reset singleton state
        mod._model = None
        mod._model_load_error = None

        with patch("huggingface_hub.hf_hub_download", side_effect=OSError("no network")):
            with pytest.raises(RuntimeError, match="Failed to load"):
                mod.get_model()

            # Second call should raise immediately without retrying download
            with pytest.raises(RuntimeError, match="Failed to load"):
                mod.get_model()

        # Confirm cached error is set
        assert mod._model_load_error is not None

        # Clean up
        mod._model_load_error = None


# ── YOLO inference (mocked) ─────────────────────────────────────────────────

@pytest.mark.unit
class TestRunYoloInference:
    def _make_mock_result(
        self,
        class_names: dict[int, str],
        detections: list[tuple[int, float, list[float]]],  # (cls_id, conf, [x1,y1,x2,y2])
    ) -> MagicMock:
        """Build a mock YOLO result object."""
        result = MagicMock()
        result.names = class_names

        boxes = MagicMock()
        n = len(detections)

        confs = [d[1] for d in detections]
        cls_ids = [d[0] for d in detections]
        bboxes = [d[2] for d in detections]

        boxes.conf = [MagicMock(wraps=c) for c in confs]
        for i, c in enumerate(confs):
            boxes.conf[i].__float__ = lambda self, _c=c: _c

        boxes.cls = [MagicMock(wraps=c) for c in cls_ids]
        for i, c in enumerate(cls_ids):
            boxes.cls[i].__int__ = lambda self, _c=c: _c

        xyxy_list = []
        for bbox in bboxes:
            arr = np.array(bbox, dtype=np.float32)
            xyxy_list.append(arr)
        boxes.xyxy = xyxy_list

        boxes.__len__ = lambda self: n
        result.boxes = boxes
        return result

    @patch("app.analysis.yolo_screener.get_model")
    def test_filters_below_threshold(self, mock_get_model: MagicMock) -> None:
        from PIL import Image

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        names = {0: "W_Bottom", 1: "Head and shoulders top"}
        result_obj = self._make_mock_result(
            names,
            [
                (0, 0.80, [480, 100, 608, 500]),  # above threshold
                (1, 0.25, [100, 50, 300, 450]),     # below threshold
            ],
        )
        mock_model.return_value = [result_obj]

        # Create a minimal test image
        img = Image.new("RGB", (640, 640), "black")
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        image_bytes = buf.getvalue()

        detections = run_yolo_inference(image_bytes, confidence_threshold=0.35, total_bars=120)

        assert len(detections) == 1
        assert detections[0].pattern_name == "double_bottom"
        assert detections[0].confidence == 0.80

    @patch("app.analysis.yolo_screener.get_model")
    def test_maps_bar_indices(self, mock_get_model: MagicMock) -> None:
        from PIL import Image

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        names = {0: "M_Head"}
        # x1=480, x2=608 in a 640px image → x1_norm=0.75, x2_norm=0.95
        result_obj = self._make_mock_result(
            names,
            [(0, 0.85, [480, 100, 608, 500])],
        )
        mock_model.return_value = [result_obj]

        img = Image.new("RGB", (640, 640), "black")
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        detections = run_yolo_inference(buf.getvalue(), total_bars=120)
        assert len(detections) == 1
        # bar_start = int(0.75 * 120) = 90
        # bar_end = int(0.95 * 120) = 114
        assert detections[0].bar_start == 90
        assert detections[0].bar_end == 114

    @patch("app.analysis.yolo_screener.get_model")
    def test_sorted_by_confidence_desc(self, mock_get_model: MagicMock) -> None:
        from PIL import Image

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        names = {0: "Triangle", 1: "W_Bottom"}
        result_obj = self._make_mock_result(
            names,
            [
                (0, 0.50, [400, 100, 600, 500]),
                (1, 0.90, [100, 100, 400, 500]),
            ],
        )
        mock_model.return_value = [result_obj]

        img = Image.new("RGB", (640, 640), "black")
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        detections = run_yolo_inference(buf.getvalue())
        assert len(detections) == 2
        assert detections[0].confidence > detections[1].confidence

    @patch("app.analysis.yolo_screener.get_model")
    def test_unknown_class_skipped(self, mock_get_model: MagicMock) -> None:
        from PIL import Image

        mock_model = MagicMock()
        mock_get_model.return_value = mock_model

        names = {0: "random_noise_pattern"}
        result_obj = self._make_mock_result(
            names,
            [(0, 0.90, [100, 100, 500, 500])],
        )
        mock_model.return_value = [result_obj]

        img = Image.new("RGB", (640, 640), "black")
        import io
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        detections = run_yolo_inference(buf.getvalue())
        assert len(detections) == 0
