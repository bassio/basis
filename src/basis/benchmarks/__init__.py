"""
Basis benchmark suite (ROADMAP-PERFORMANCE.md, T0 — Measure First).

A small, stdlib-first harness plus a set of *realistic* scenarios that exercise
the framework's hot paths the way the target apps (dashboards, internal tools,
data apps) actually hit them:

* mounting N components
* mutating M state fields in one handler
* rendering a 1k / 10k-row loop (full LIS reconcile)
* hydrating an SSR page (mount + hydration IDs + initial-state serialization)
* fanning a store out to 50 subscribers
* template / expression parsing (the T1 #1 / #3 hot path baseline)

Run from anywhere with::

    basis bench

Or, inside the framework repo, through pytest (opt-in, skipped by default)::

    pytest tests/benchmarks --bench

Every scenario records **median + p95** (not just a single best-case sample),
so a regression in the distribution shows up, not just the lucky path.

This is an engineering tool AND a CI gate. The regression *thresholds* land
after T1 (the first set of optimizations) so they encode the improved numbers;
the harness and scenarios are the measurable baseline that gates them.
"""

from basis.benchmarks.harness import (
    Scenario,
    Timing,
    time_scenario,
    run_suite,
    format_plain_summary,
    to_dict,
)
from basis.benchmarks.scenarios import SCENARIOS

__all__ = [
    "Scenario",
    "Timing",
    "time_scenario",
    "run_suite",
    "format_plain_summary",
    "to_dict",
    "SCENARIOS",
]
