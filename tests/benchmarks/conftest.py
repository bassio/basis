"""
Pytest integration for the Basis benchmark suite (ROADMAP-PERFORMANCE.md T0).

Benchmarks are opt-in so normal test runs stay fast and deterministic:
``pytest`` skips them unless ``--bench`` is passed. Run with::

    pytest tests/benchmarks --bench
    pytest tests/benchmarks --bench --bench-repeats 3
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--bench",
        action="store_true",
        default=False,
        help="Run the Basis benchmark suite (skipped by default).",
    )
    parser.addoption(
        "--bench-repeats",
        type=int,
        default=1,
        help="Timed iterations per benchmark scenario (median/p95 taken over them).",
    )


def pytest_collection_modifyitems(config, items):
    """Skip benchmark-marked tests unless ``--bench`` is passed."""
    if config.getoption("--bench"):
        return
    skip = pytest.mark.skip(reason="benchmark — run with `--bench` to enable")
    for item in items:
        if "benchmark" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def bench_repeats(request) -> int:
    """Number of timed iterations per scenario (defaults to 1 under pytest)."""
    return request.config.getoption("--bench-repeats")
