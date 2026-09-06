"""
Timing harness for the Basis benchmark suite.

Design notes
------------
* Stdlib-only (``time.perf_counter`` / ``statistics``) so the suite runs in CI
  with zero extra dependencies; ``rich`` (already a framework dependency) is
  used only by the ``basis bench`` CLI for the pretty table, never here.
* Each scenario declares a **setup** (fresh fixture per iteration) and a **run**
  (the timed body). A fresh fixture per iteration keeps global registries
  isolated and avoids measuring accumulated state.
* Results report **median + p95** across repeat runs — the roadmap's explicit
  requirement ("Record median + p95") — plus mean/min/max/stdev for context.
  The median is robust to scheduling noise; p95 catches the tail that hurts
  perceived responsiveness.
"""

from __future__ import annotations

import gc
import statistics
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

#: Default number of timed iterations per scenario.
DEFAULT_REPEATS = 5


@dataclass
class Scenario:
    """A named, timed workload.

    ``setup`` is called once per iteration to build a *fresh* fixture (so
    registries/state never leak between samples); ``run(fixture)`` is the timed
    body. ``verify`` (optional) runs once after the first setup to assert the
    workload actually does the right thing — a benchmark that quietly measures
    a no-op is worse than no benchmark.
    """

    name: str
    desc: str
    setup: Callable[[], Any]
    run: Callable[[Any], None]
    scale: str = ""
    repeats: int = DEFAULT_REPEATS
    verify: Optional[Callable[[Any], None]] = None
    #: True → ``gc.collect()`` before each timed iteration so one iteration's
    #: allocation pressure does not bleed into the next sample.
    gc_between: bool = True

    def __post_init__(self):
        if not self.name or not callable(self.setup) or not callable(self.run):
            raise ValueError(
                f"Scenario {self.name!r} needs a name, a callable setup() and "
                f"a callable run()"
            )


@dataclass
class Timing:
    """Timing result for one scenario: raw samples (seconds) + derived stats."""

    name: str
    desc: str
    scale: str
    samples_s: list[float]

    @property
    def n(self) -> int:
        return len(self.samples_s)

    def _ms(self, s: float) -> float:
        return s * 1000.0

    @property
    def median_ms(self) -> float:
        return self._ms(statistics.median(self.samples_s))

    @property
    def p95_ms(self) -> float:
        return self._ms(_percentile(self.samples_s, 95))

    @property
    def mean_ms(self) -> float:
        return self._ms(statistics.mean(self.samples_s))

    @property
    def min_ms(self) -> float:
        return self._ms(min(self.samples_s))

    @property
    def max_ms(self) -> float:
        return self._ms(max(self.samples_s))

    @property
    def stdev_ms(self) -> float:
        if self.n < 2:
            return 0.0
        return self._ms(statistics.stdev(self.samples_s))


def _percentile(samples: list[float], p: float) -> float:
    """Nearest-rank percentile. ``samples`` is expected non-empty."""
    if not samples:
        return 0.0
    ordered = sorted(samples)
    rank = max(1, round(p / 100.0 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def time_scenario(scenario: Scenario, repeats: Optional[int] = None) -> Timing:
    """Time ``scenario`` over ``repeats`` fresh iterations.

    Runs one untimed warm-up (setup → verify → run) so lazy imports / one-time
    caches are warm before the first sample, then times ``repeats`` fresh
    iterations and returns a :class:`Timing`.
    """
    repeats = repeats if repeats is not None else scenario.repeats

    # Warm-up: prove the workload runs and does the right thing.
    fixture = scenario.setup()
    try:
        scenario.run(fixture)
        if scenario.verify is not None:
            scenario.verify(fixture)
    finally:
        del fixture
        if scenario.gc_between:
            gc.collect()

    samples: list[float] = []
    for _ in range(repeats):
        if scenario.gc_between:
            gc.collect()
        fixture = scenario.setup()
        try:
            t0 = time.perf_counter()
            scenario.run(fixture)
            samples.append(time.perf_counter() - t0)
        finally:
            del fixture
            if scenario.gc_between:
                gc.collect()

    return Timing(
        name=scenario.name,
        desc=scenario.desc,
        scale=scenario.scale,
        samples_s=samples,
    )


def run_suite(
    scenarios: Iterable[Scenario],
    repeats: Optional[int] = None,
    names: Optional[Iterable[str]] = None,
) -> list[Timing]:
    """Time a suite of scenarios, optionally filtered by ``names`` (substring
    match, case-insensitive). Returns :class:`Timing` results in order."""
    wanted = None
    if names is not None:
        wanted = [n.lower() for n in names]

    results: list[Timing] = []
    for sc in scenarios:
        if wanted is not None and not any(w in sc.name.lower() for w in wanted):
            continue
        results.append(time_scenario(sc, repeats=repeats))
    return results


def to_dict(results: list[Timing]) -> dict:
    """Serialize results to a plain dict (for ``--json`` output)."""
    return {
        "scenarios": [
            {
                "name": r.name,
                "desc": r.desc,
                "scale": r.scale,
                "n": r.n,
                "median_ms": round(r.median_ms, 3),
                "p95_ms": round(r.p95_ms, 3),
                "mean_ms": round(r.mean_ms, 3),
                "min_ms": round(r.min_ms, 3),
                "max_ms": round(r.max_ms, 3),
                "stdev_ms": round(r.stdev_ms, 3),
            }
            for r in results
        ]
    }


def format_plain_summary(results: list[Timing]) -> str:
    """A plain-text summary (used by pytest wrappers; no ``rich`` dependency)."""
    lines = []
    header = f"{'scenario':<34} {'scale':<20} {'median ms':>10} {'p95 ms':>10}"
    lines.append(header)
    lines.append("-" * len(header))
    for r in results:
        lines.append(
            f"{r.name:<34} {r.scale:<20} {r.median_ms:>10.2f} {r.p95_ms:>10.2f}"
        )
    lines.append("")
    lines.append("(median + p95 over {} iterations per scenario)".format(
        results[0].n if results else 0
    ))
    return "\n".join(lines)
