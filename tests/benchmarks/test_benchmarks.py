"""
Pytest wrapper around the Basis benchmark suite (ROADMAP-PERFORMANCE.md T0).

Every scenario in :data:`basis.benchmarks.scenarios.SCENARIOS` becomes a
parameterized test. The harness's ``verify`` hook runs during the warm-up, so a
scenario that stops doing real work fails the test — a benchmark that measures
a no-op is worse than no benchmark.

Run with::

    pytest tests/benchmarks --bench
    pytest tests/benchmarks --bench --bench-repeats 3 -k loop

(Without ``--bench`` these tests are skipped; see ``conftest.py``.)
"""

from __future__ import annotations

import pytest

from basis.benchmarks import SCENARIOS, time_scenario

pytestmark = pytest.mark.benchmark


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda s: s.name)
def test_benchmark_scenario(scenario, bench_repeats: int):
    """Time one realistic scenario and report median + p95.

    ``time_scenario`` already runs the scenario's ``verify`` hook (post warm-up
    run), so an assertion failure here means the workload is no longer doing
    what its name says — not a timing failure.
    """
    timing = time_scenario(scenario, repeats=bench_repeats)

    print(
        f"\n  {scenario.name} ({scenario.scale}): "
        f"median={timing.median_ms:.2f}ms  p95={timing.p95_ms:.2f}ms  "
        f"mean={timing.mean_ms:.2f}ms  (n={timing.n})"
    )

    # A timing can never legitimately be negative; this is a canary, not a
    # regression gate (thresholds land with T1).
    assert timing.median_ms >= 0.0
    assert timing.p95_ms >= 0.0
