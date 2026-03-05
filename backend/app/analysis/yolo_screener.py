"""YOLOv8 chart pattern detection using foduucom/stockmarket-pattern-detection-yolov8.

Loads the model once as a singleton, runs inference on rendered chart images,
and returns normalized detections with pattern names and directional signals.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass

log = logging.getLogger(__name__)

# HuggingFace model coordinates
_HF_REPO_ID = "foduucom/stockmarket-pattern-detection-yolov8"
_HF_MODEL_FILENAME = "model.pt"

# ── Pattern name mapping ─────────────────────────────────────────────────────
# The foduucom/stockmarket-pattern-detection-yolov8 model detects 6 classes:
#   'Head and shoulders bottom', 'Head and shoulders top',
#   'M_Head', 'StockLine', 'Triangle', 'W_Bottom'
# We map these to canonical snake_case names.
_CLASS_NAME_MAP: dict[str, str] = {
    # Actual model class names (lowercase for lookup)
    "head and shoulders bottom": "inverse_head_and_shoulders",
    "head and shoulders top": "head_and_shoulders",
    "m_head": "double_top",
    "stockline": "trendline",
    "triangle": "triangle",
    "w_bottom": "double_bottom",
    # Alternative forms that might appear
    "head_and_shoulders_bottom": "inverse_head_and_shoulders",
    "head_and_shoulders_top": "head_and_shoulders",
    "head and shoulders": "head_and_shoulders",
    "inverse head and shoulders": "inverse_head_and_shoulders",
    "double top": "double_top",
    "double_top": "double_top",
    "double bottom": "double_bottom",
    "double_bottom": "double_bottom",
}

PATTERN_DIRECTIONS: dict[str, str] = {
    "head_and_shoulders": "bearish",
    "inverse_head_and_shoulders": "bullish",
    "double_top": "bearish",
    "double_bottom": "bullish",
    "triangle": "neutral",
    "trendline": "neutral",
}

DIRECTION_SIGN: dict[str, float] = {
    "bullish": 1.0,
    "bearish": -1.0,
    "neutral": 0.0,
}

# Geometric patterns weight: 0.8 (< harmonics 1.0, > candlesticks 0.7)
GEOMETRIC_PATTERN_WEIGHT = 0.8

# Confidence thresholds
LOG_THRESHOLD = 0.20
DEFAULT_CONFIDENCE_THRESHOLD = 0.35

# Recency decay: patterns ending more than this many bars from the chart end decay to 0
RECENCY_DECAY_BARS = 5


@dataclass
class YoloDetection:
    """A single YOLOv8 pattern detection."""

    pattern_name: str
    confidence: float
    bbox: tuple[float, float, float, float]  # normalized (x1, y1, x2, y2)
    direction: str
    bar_start: int
    bar_end: int
    price_top: float | None = None     # upper price boundary of the pattern
    price_bottom: float | None = None  # lower price boundary of the pattern


# ── Model singleton ──────────────────────────────────────────────────────────

_model: object | None = None
_model_load_error: str | None = None


def get_model() -> object:
    """Load the YOLOv8 model once and cache it.

    Downloads weights from HuggingFace on first call, then loads via ultralytics.
    Caches permanent load failures to avoid retrying on every symbol.
    """
    global _model, _model_load_error

    if _model is not None:
        return _model

    if _model_load_error is not None:
        raise RuntimeError(_model_load_error)

    try:
        from huggingface_hub import hf_hub_download
        from ultralytics import YOLO

        log.info("Downloading YOLOv8 model weights from %s ...", _HF_REPO_ID)
        model_path = hf_hub_download(repo_id=_HF_REPO_ID, filename=_HF_MODEL_FILENAME)
        log.info("Loading YOLOv8 model from %s", model_path)
        _model = YOLO(model_path)
        log.info("YOLOv8 model loaded successfully")
        return _model
    except Exception as exc:
        _model_load_error = f"Failed to load YOLOv8 model: {exc}"
        log.error(_model_load_error)
        raise RuntimeError(_model_load_error) from exc


def _normalize_class_name(raw_name: str) -> str | None:
    """Normalize a YOLO class name to our canonical snake_case form."""
    key = raw_name.strip().lower()
    if key in _CLASS_NAME_MAP:
        return _CLASS_NAME_MAP[key]
    # Try converting to snake_case
    snake = re.sub(r"[\s\-]+", "_", key)
    if snake in PATTERN_DIRECTIONS:
        return snake
    return None


def run_yolo_inference(
    image: bytes,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
    total_bars: int = 120,
    price_min: float | None = None,
    price_max: float | None = None,
) -> list[YoloDetection]:
    """Run YOLOv8 inference on a chart image.

    Parameters
    ----------
    image : bytes
        PNG image data (640x640 candlestick chart).
    confidence_threshold : float
        Minimum confidence to include in results (default 0.35).
        Detections above LOG_THRESHOLD (0.20) are logged for tuning.
    total_bars : int
        Number of bars in the chart, used to map bbox x-coords to bar indices.
    price_min : float | None
        Lower y-axis limit of the rendered chart (from ax.get_ylim()).
        When provided with price_max, bbox y-coords are converted to prices.
    price_max : float | None
        Upper y-axis limit of the rendered chart (from ax.get_ylim()).

    Returns
    -------
    list[YoloDetection]
        Detections above confidence_threshold, sorted by confidence descending.
    """
    from PIL import Image

    model = get_model()

    # Load image from bytes
    img = Image.open(io.BytesIO(image))
    img_width = img.width

    # Run inference
    results = model(img, verbose=False)

    detections: list[YoloDetection] = []

    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue

        for i in range(len(boxes)):
            conf = float(boxes.conf[i])
            if conf < LOG_THRESHOLD:
                continue

            # Get class name
            cls_id = int(boxes.cls[i])
            raw_name = result.names.get(cls_id, f"class_{cls_id}")
            pattern_name = _normalize_class_name(raw_name)

            if pattern_name is None:
                log.debug("Unknown YOLO class: %s (conf=%.3f)", raw_name, conf)
                continue

            # Get bbox (xyxy format, pixel coords)
            box = boxes.xyxy[i]
            if hasattr(box, "cpu"):
                box = box.cpu().numpy()
            x1, y1, x2, y2 = float(box[0]), float(box[1]), float(box[2]), float(box[3])

            # Normalize bbox to 0-1
            x1_norm = x1 / img_width
            x2_norm = x2 / img_width
            y1_norm = y1 / img.height
            y2_norm = y2 / img.height

            # Map x-coordinates to bar indices
            bar_start = int(x1_norm * total_bars)
            bar_end = int(x2_norm * total_bars)
            bar_start = max(0, min(total_bars - 1, bar_start))
            bar_end = max(0, min(total_bars - 1, bar_end))

            direction = PATTERN_DIRECTIONS.get(pattern_name, "neutral")

            # Convert normalized y-coords to prices when price range is available.
            # y1_norm is the TOP of the bbox (smaller pixel value = higher price).
            # y2_norm is the BOTTOM of the bbox (larger pixel value = lower price).
            # Formula: price = price_max - y_norm * (price_max - price_min)
            det_price_top: float | None = None
            det_price_bottom: float | None = None
            if price_min is not None and price_max is not None:
                price_range = price_max - price_min
                det_price_top = round(price_max - y1_norm * price_range, 6)
                det_price_bottom = round(price_max - y2_norm * price_range, 6)

            detection = YoloDetection(
                pattern_name=pattern_name,
                confidence=round(conf, 4),
                bbox=(round(x1_norm, 4), round(y1_norm, 4), round(x2_norm, 4), round(y2_norm, 4)),
                direction=direction,
                bar_start=bar_start,
                bar_end=bar_end,
                price_top=det_price_top,
                price_bottom=det_price_bottom,
            )

            # Log everything above LOG_THRESHOLD for threshold tuning
            log.info(
                "YOLO detection: %s (conf=%.3f, dir=%s, bars=%d-%d)%s",
                pattern_name,
                conf,
                direction,
                bar_start,
                bar_end,
                "" if conf >= confidence_threshold else " [below threshold]",
            )

            if conf >= confidence_threshold:
                detections.append(detection)

    detections.sort(key=lambda d: d.confidence, reverse=True)
    return detections


def compute_yolo_signals(
    detections: list[YoloDetection],
    total_bars: int = 120,
) -> dict[str, float]:
    """Convert YOLOv8 detections into normalized signal scores.

    Returns a dict compatible with the scoring engine's signal format.
    Uses the highest-confidence detection for scoring.

    Score = confidence x direction_sign x GEOMETRIC_PATTERN_WEIGHT x recency_weight
    """
    if not detections:
        return {
            "yolo_pattern_detected": 0.0,
            "yolo_pattern_score": 0.0,
            "yolo_pattern_confidence": 0.0,
        }

    best = detections[0]  # Already sorted by confidence desc

    # Recency weighting: patterns ending far from chart end decay to 0
    bars_from_end = total_bars - 1 - best.bar_end
    recency_weight = max(0.0, 1.0 - bars_from_end / RECENCY_DECAY_BARS)

    direction_sign = DIRECTION_SIGN.get(best.direction, 0.0)
    score = best.confidence * direction_sign * GEOMETRIC_PATTERN_WEIGHT * recency_weight
    score = max(-1.0, min(1.0, score))

    return {
        "yolo_pattern_detected": 1.0,
        "yolo_pattern_score": round(score, 6),
        "yolo_pattern_confidence": round(best.confidence, 4),
    }
