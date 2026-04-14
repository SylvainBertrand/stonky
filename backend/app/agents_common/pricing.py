"""Model pricing table for Execution Log cost estimation.

Stores per-model input/output rates (USD per million tokens) and provides a
single helper to compute estimated cost from token counts.

Rates are list-price (no caching discount) — acceptable precision for the
Execution Log; the goal is order-of-magnitude spend attribution, not billing
reconciliation.

Usage::

    from app.agents_common.pricing import estimate_cost_usd

    cost = estimate_cost_usd(
        model="claude-sonnet-4-6",
        input_tokens=10_000,
        output_tokens=500,
    )
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _ModelRate:
    input_per_million: float  # USD per 1M input tokens
    output_per_million: float  # USD per 1M output tokens


# ---------------------------------------------------------------------------
# Pricing table (TC-011) — update when Anthropic changes list prices.
# Keys are the model string written to the Execution Log "Model" field.
# ---------------------------------------------------------------------------

MODEL_RATES: dict[str, _ModelRate] = {
    "claude-sonnet-4-6": _ModelRate(input_per_million=3.00, output_per_million=15.00),
    "claude-opus-4-6": _ModelRate(input_per_million=15.00, output_per_million=75.00),
    "claude-haiku-4-5": _ModelRate(input_per_million=1.00, output_per_million=5.00),
    # Stonky deterministic runs — no LLM cost
    "stonky-engine": _ModelRate(input_per_million=0.0, output_per_million=0.0),
}


def estimate_cost_usd(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> float:
    """Return estimated cost in USD for a given model + token counts.

    Returns 0.0 for unknown models (safe default; logs nothing — caller decides
    whether to warn).  Rounds to 6 decimal places to avoid floating-point noise
    at very small values while preserving 4-significant-figure precision at the
    dollar scale used in the Execution Log.
    """
    rate = MODEL_RATES.get(model)
    if rate is None:
        return 0.0
    cost = (
        input_tokens * rate.input_per_million + output_tokens * rate.output_per_million
    ) / 1_000_000
    return round(cost, 6)
