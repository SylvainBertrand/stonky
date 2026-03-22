"""Strategy registry — maps string names to strategy classes."""

from app.backtesting.strategies.custom_strategy import CustomStrategy
from app.backtesting.strategies.indicator_strategies import (
    EMACrossoverStrategy,
    MACDCrossStrategy,
    RSIThresholdStrategy,
    SupertrendStrategy,
)
from app.backtesting.strategies.pattern_strategies import YOLOPatternStrategy
from app.backtesting.strategies.profile_strategies import (
    HarmonicSetupStrategy,
    MeanReversionStrategy,
    MomentumBreakoutStrategy,
    TrendFollowingStrategy,
)

STRATEGY_REGISTRY: dict[str, type] = {
    "ema_crossover": EMACrossoverStrategy,
    "rsi_threshold": RSIThresholdStrategy,
    "macd_cross": MACDCrossStrategy,
    "supertrend": SupertrendStrategy,
    "momentum_breakout": MomentumBreakoutStrategy,
    "trend_following": TrendFollowingStrategy,
    "mean_reversion": MeanReversionStrategy,
    "harmonic_setup": HarmonicSetupStrategy,
    "yolo_pattern": YOLOPatternStrategy,
    "custom": CustomStrategy,
}


def create_strategy(strategy_type: str, parameters: dict):
    """Create a strategy instance from a type string and parameter dict."""
    cls = STRATEGY_REGISTRY.get(strategy_type)
    if cls is None:
        raise ValueError(
            f"Unknown strategy: {strategy_type}. Available: {list(STRATEGY_REGISTRY.keys())}"
        )
    if strategy_type == "custom":
        return cls(config=parameters)
    return cls(**parameters)
