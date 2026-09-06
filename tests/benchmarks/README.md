# Basis Benchmark Suite — T0 (Measure First)

This is the **T0 — Measure First** deliverable from
[`ROADMAP-PERFORMANCE.md`](../../ROADMAP-PERFORMANCE.md): a harness plus
realistic scenarios that record **median + p95** for the framework's hot paths,
so no optimization lands before it can be measured, and so regressions can fail
CI instead of users.

The engine and scenarios live in **`src/basis/benchmarks/`** (bundled with the
package so `basis bench` works from any project). The files in this directory
are the pytest integration + notes.

---

## Running

```bash
# Full suite, 5 iterations per scenario (the default)
basis bench

# Fast smoke (1 iteration each)
basis bench --quick

# Only loop-related scenarios
basis bench -s loop

# Machine-readable output for CI
basis bench --json
basis bench -n 3 --json
```

Or via pytest (opt-in — **skipped by default** so normal test runs stay fast):

```bash
pytest tests/benchmarks --bench
pytest tests/benchmarks --bench --bench-repeats 3 -k loop
```

Each scenario has a `verify` hook that runs during the warm-up: a scenario that
stops doing real work (silently becomes a no-op) **fails**, so the numbers stay
honest.

---

## Scenarios & baseline (2026-08-30, CPython 3.14 on the dev machine)

> Medians are over 3 iterations. Numbers are a *reference point* to compare
> against after T1 lands — not hard gates yet (gates come with T1, see below).

| scenario | scale | median | p95 | measures |
|---|---|---|---|---|
| `mount_50_components` | 50 instances | 61 ms | 109 ms | real `mount()` path incl. **per-mount template re-analysis** (T1 #11/#15 target) |
| `mount_200_components` | 200 instances | 198 ms | 200 ms | same, scaled (~1 ms/instance) |
| `mutate_10_fields_sequential` | 10 fields | 0.06 ms | 0.12 ms | one handler, 10 DAG passes (T1 #6 target) |
| `mutate_25_fields_sequential` | 25 fields | 0.11 ms | 0.18 ms | one handler, 25 DAG passes |
| `mutate_10_fields_refrain` | 10 fields batched | 0.04 ms | 0.05 ms | same work, explicit `refrain()` — the implicit-batching target |
| `loop_render_1k` | 1,000 rows | 36 ms | 36 ms | full LIS reconcile + per-item bindings/effects |
| `loop_render_10k` | 10,000 rows | **1425 ms** | 1607 ms | the big one — per-item setup dominates (T1 #7, T2 #21) |
| `ssr_hydrate_1k` | 1 page / 1k rows | 53 ms | 53 ms | SSR render: mount + hydration IDs + state serialization |
| `store_fanout_50` | 50 subscribers | 0.12 ms | 0.12 ms | store→component notification cascade |
| `store_fanout_100` | 100 subscribers | 0.21 ms | 0.21 ms | same, scaled |
| `template_format_1k` | 1,000 updates | 17 ms | 18 ms | `safe_format` per-update cost ≈ **17 µs/update** (T1 #1) |
| `template_analyze_1k` | 1,000 templates | 20 ms | 20 ms | `extract_dependencies` ≈ **20 µs/template** (T1 #1/#3) |

**Read on the numbers:** mounting is ~1 ms/instance *including* re-parsing the
whole template each time (the per-instance re-analysis in `initialize` is the
bulk of it — T1 #11/#15). A 10k loop is 1.4 s server-side; the per-item binding
+ effect setup is the cost (T1 #7 + the virtualized loop in T2 #21 are the
fixes). Batching 10 mutations cuts time ~35% and the gap widens with M (T1 #6).
`template_format_1k` ≈ 17 µs/update is the T1 #1 pre-split target (parse the
template once, evaluate only the fields per update).

---

## Server profiling (T0)

Two complementary ways to find server-side hot paths (SSR + action endpoints):

- **`basis dev --profile`** — runs uvicorn under `cProfile`, prints a hot-path
  summary (top cumulative-time frames in your app / the framework) on shutdown,
  and leaves `.basis-profile.pstats` in the project for deeper tooling:

  ```bash
  basis dev --profile
  # hit some routes, Ctrl-C
  # → 🔥 Hot-path summary (top cumulative time)
  # Full profile saved to .basis-profile.pstats — open with `snakeviz`.
  ```

- **`py-spy`** — attach to a *running* server for a sampling profile with zero
  code changes (great for a server already under load):

  ```bash
  py-spy record -o profile.svg --pid <uvicorn-pid> --duration 30
  ```

- **`cProfile` around a single SSR render** — the `ssr_hydrate_1k` scenario is a
  convenient workload:

  ```bash
  python -c "
  import cProfile, pstats
  from basis.benchmarks import SCENARIOS, time_scenario
  sc = next(s for s in SCENARIOS if s.name == 'ssr_hydrate_1k')
  cProfile.runctx('time_scenario(sc, repeats=1)', globals(), locals(), 'ssr.pstats')
  pstats.Stats('ssr.pstats').strip_dirs().sort_stats('cumulative').print_stats(30)
  "
  ```

---

## Client profiling (T0)

The client runs CPython via Pyodide, so the *same* Python profiling tools work
inside the browser, plus the browser's own Performance panel for DOM/layout.

**Pyodide `sys.setprofile` counters** — count Python function calls / time in
the boot + mount window (add to your app's client entrypoint, or paste into the
PyScript console):

```python
import sys, time
_counts = {}
_start = time.time()
def _prof(frame, event, arg):
    name = frame.f_code.co_name
    _counts[name] = _counts.get(name, 0) + 1
sys.setprofile(_prof)
# ... let the app boot + mount ...
sys.setprofile(None)
print("elapsed", time.time() - _start)
print(sorted(_counts.items(), key=lambda kv: -kv[1])[:20])
```

**Browser DevTools "Performance" recipe** (for DOM/layout — PyScript calls show
as a single thread but JS/DOM work is visible):

1. Open the page, open DevTools → Performance, press **Record**, reload, stop.
2. Look for: long **yellow (script)** tasks = Pyodide evaluating Python;
   **purple (layout)** spans = DOM writes triggering reflow; **gaps** where the
   main thread is idle during boot.
3. Correlate with the `basis bench` numbers: e.g. a page whose SSR equivalent
   mounts 200 components should feel like the `mount_200_components` cost, and
   `loop_render_10k` shows why a 10k table janks until T2 #21 lands.

**Expected TTI budget.** The dominant client cost is boot (Pyodide download +
compile) — the T3 #28 goal is a **repeat-visit page interactive in under 1s**
(cached Pyodide + PYC + minimized VFS). As a rule of thumb for T0: budget the
*framework* work per interaction at roughly the server-side numbers above
(µs–ms scale); anything that scales superlinearly with rows/components (today:
10k-loop render) is the thing to fix, not the thing to buy hardware for.

---

## CI regression gates (after T1)

Threshold tests are **deliberately not** added yet: T0 exists to give T1 a
baseline, and gating on the *current* numbers would freeze in the pre-T1 costs.
Once T1 lands, add a `tests/benchmarks/test_gates.py` that asserts the *new*
medians, e.g.:

```python
# test_gates.py — AFTER T1, encoding improved numbers (illustrative only)
import pytest
from basis.benchmarks import SCENARIOS, time_scenario

GATES = {
    "mount_200_components": 120.0,   # ms, p95
    "loop_render_10k":        900.0, # ms, p95
    "template_format_1k":       8.0, # ms, p95  (T1 #1 pre-split)
}

@pytest.mark.benchmark
def test_regression_gates():
    for sc in SCENARIOS:
        gate = GATES.get(sc.name)
        if gate is None:
            continue
        t = time_scenario(sc, repeats=3)
        assert t.p95_ms < gate, f"{sc.name} p95={t.p95_ms:.1f}ms exceeded gate {gate}ms"
```

Wire it into CI (skipped unless `--bench`): `pytest tests/benchmarks --bench`.
Run it on a reasonably pinned machine (CI runners are fine; just don't compare
across wildly different CPUs — gate on the *same* runner's historical numbers
via a stored baseline, not on the numbers in this README).
