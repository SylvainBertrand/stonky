"""
Pytest plugin for golden file management.

Usage:
    pytest tests/ta_validation/                    # compare against golden files
    pytest tests/ta_validation/ --update-golden     # regenerate golden files from current output

Golden files live in tests/fixtures/golden/{indicator_name}.json
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-golden",
        action="store_true",
        default=False,
        help="Regenerate golden files from current indicator output instead of comparing.",
    )


@pytest.fixture
def update_golden(request: pytest.FixtureRequest) -> bool:
    """Fixture that returns True if --update-golden was passed."""
    return request.config.getoption("--update-golden")


@pytest.fixture
def golden_dir() -> Path:
    """Path to golden files directory."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    return GOLDEN_DIR


def load_golden(indicator_name: str) -> dict[str, Any] | None:
    """Load a golden file by indicator name. Returns None if not found."""
    path = GOLDEN_DIR / f"{indicator_name}.json"
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_golden(
    indicator_name: str,
    params: dict[str, Any],
    snapshot: str,
    values: list[dict[str, Any]],
    tolerance: float = 1e-6,
) -> Path:
    """Write a golden file for an indicator."""
    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = GOLDEN_DIR / f"{indicator_name}.json"
    data = {
        "indicator": indicator_name,
        "params": params,
        "snapshot": snapshot,
        "generated_at": datetime.now(UTC).isoformat(),
        "tolerance": tolerance,
        "values": values,
    }
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    return path


def assert_golden(
    indicator_name: str,
    actual_values: list[dict[str, Any]],
    update_mode: bool,
    params: dict[str, Any] | None = None,
    snapshot: str = "unknown",
    tolerance: float = 1e-6,
) -> None:
    """
    Compare actual indicator output against golden file.

    If update_mode is True, writes the golden file instead of comparing.
    If the golden file doesn't exist and update_mode is False, fails with
    a helpful message.
    """
    if update_mode:
        path = save_golden(
            indicator_name=indicator_name,
            params=params or {},
            snapshot=snapshot,
            values=actual_values,
            tolerance=tolerance,
        )
        pytest.skip(f"Golden file updated: {path}")
        return

    golden = load_golden(indicator_name)
    if golden is None:
        pytest.fail(
            f"Golden file not found for '{indicator_name}'. "
            f"Run with --update-golden to generate it."
        )

    tol = golden.get("tolerance", tolerance)
    expected = golden["values"]

    assert len(actual_values) == len(expected), (
        f"Length mismatch for {indicator_name}: got {len(actual_values)}, expected {len(expected)}"
    )

    for i, (actual, exp) in enumerate(zip(actual_values, expected)):
        assert actual["time"] == exp["time"], (
            f"Time mismatch at index {i} for {indicator_name}: "
            f"got {actual['time']}, expected {exp['time']}"
        )

        # Compare all numeric fields within tolerance
        for key in exp:
            if key == "time":
                continue
            if exp[key] is None:
                assert actual.get(key) is None, (
                    f"Expected None for {indicator_name}[{i}].{key}, got {actual.get(key)}"
                )
            elif isinstance(exp[key], (int, float)):
                actual_val = actual.get(key)
                assert actual_val is not None, (
                    f"Missing key {key} at index {i} for {indicator_name}"
                )
                assert actual_val == pytest.approx(exp[key], abs=tol), (
                    f"Value mismatch for {indicator_name}[{i}].{key}: "
                    f"got {actual_val}, expected {exp[key]} (tol={tol})"
                )
