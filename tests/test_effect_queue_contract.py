"""
Contract harness for the effect-queue overhaul
(HYDRATION-REPOINT-RACE-FIX-PLAN.md §5 — invariants I1–I8).

STATUS (2026-09-02): P1 (owner-scoped pending queues) + P2 (deterministic
wave-based flush) LANDED together. The old module-global `_dirty_effects` bag is
GONE; each `DependencyGraph` owns its `_pending` queue and every `EffectNode`
carries its `owner_graph`; the flush drains graphs in creation order (older =
store/ancestor first) in waves to quiescence. The two ordering contracts below
were RED against the old scheduler (the global-set drain interleaved graphs);
they are now the GREEN regression guard for the deterministic policy.

P3 (batch + flush-boundary primitives) LANDED: `batch()` / `ReactiveBatch` hold
all flushes for a block and drain (or `discard()`) on the outermost exit;
`ReactiveScope.pending_count()` / `discard_pending()` give owner-scoped discard.

  P1 targets (ownership, I2):
    test_effect_knows_its_owner_graph
    test_pending_work_is_attributable_to_exactly_one_graph
    test_wake_list_lists_dirty_graphs_not_effects
    test_scope_destroy_drops_its_own_pending
  P2 targets (deterministic per-graph ordering, I1) — now green guards:
    test_older_graph_effects_precede_newer_graph_effects
    test_store_effects_precede_consumer_effects
  P3 targets (batch & flush boundaries, I7) — unit scenarios, no SSR DOM:
    test_batch_holds_flushes_until_exit
    test_batch_discard_drops_pending_but_effect_stays_live
    test_scope_pending_count_and_discard_pending
    test_nested_batches_drain_only_at_outermost_exit
  GREEN guards (I3/I4/I5/I6/I8): cross-object wake-up, synchronous flush,
  at-most-once per trigger, refrain batching, quiescence / no lost update,
  prop-sync convergence.

The full SSR-hydration integration of the boundary (I7 end-to-end) is P4 and is
covered by the P5 browser harness.

Empirical note (2026-09-02): for a fixed synthetic scenario the old global set's
pop order was stable across fresh interpreter processes (object-address
layout), so cross-process stability was NOT the reliably-red contract — the
GRAPH-INTERLEAVE was. In the real app the dirty-ARRIVAL order also varies with
mount/async timing (the intermittency source), which is why the P5 browser
harness exists in addition to these unit contracts.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from basis import __file__ as _basis_init
from basis.shared.reactive import (
    DependencyGraph,
    ReactiveObject,
    ReactiveScope,
    _wake_list,
    batch,
)

_SRC = Path(_basis_init).parent.parent  # repo/src (basis lives at src/basis/)


@pytest.fixture(autouse=True)
def _clean_state():
    _wake_list.clear()
    yield
    _wake_list.clear()


# ─────────────────────────────────────────────────────────────
# subprocess runner — a fresh interpreter per run (ASLR + seed vary)
# ─────────────────────────────────────────────────────────────

def _scenario(graphs: int, n: int) -> str:
    """K graphs created in order (0..K-1), each with N effects; every effect
    depends (cross-graph) on one shared owner StateNode, so a single trigger
    dirties all K*N effects at once. Prints the execution sequence."""
    return f"""
import sys
sys.path.insert(0, {str(_SRC)!r})
from basis.shared.reactive import DependencyGraph, ReactiveObject

K = {graphs}; N = {n}
owner = ReactiveObject(); owner.x = 0
graphs = [DependencyGraph() for _ in range(K)]
seq = []
for gi, g in enumerate(graphs):
    for i in range(N):
        g.add_effect("g{{0}}_{{1}}".format(gi, i),
                     (lambda gi, i: lambda: seq.append("g{{0}}_{{1}}".format(gi, i)))(gi, i), [])
        g.nodes["g{{0}}_{{1}}".format(gi, i)].add_dependency(owner._dag.nodes["x"])
owner.x = 1
print(",".join(seq))
"""


def _run_many(code: str, runs: int = 8) -> list[str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_SRC) + os.pathsep + env.get("PYTHONPATH", "")
    outs = []
    for _ in range(runs):
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, env=env
        )
        assert result.returncode == 0, f"scenario failed:\n{result.stdout}\n{result.stderr}"
        outs.append(result.stdout.strip())
    return outs


def _blocks_are_ordered(seq: str, graphs: int) -> bool:
    """True when every token of graph g appears before every token of graph g+1
    (per-graph drain in creation order = the P2 policy)."""
    toks = seq.split(",")
    last_seen = -1
    for tok in toks:
        g = int(tok.split("_")[0][1:])
        if g < last_seen:
            return False
        last_seen = g
    return True


# ─────────────────────────────────────────────────────────────
# P1 — owner-scoped pending queues (I2)
# ─────────────────────────────────────────────────────────────

def test_effect_knows_its_owner_graph():
    """I2: every effect created via add_effect knows its owning graph, so
    pending work is attributable (never an anonymous global bag)."""
    graph = DependencyGraph()
    graph.add_effect("e", lambda: None, ["x"])
    assert graph.nodes["e"].owner_graph is graph


def test_pending_work_is_attributable_to_exactly_one_graph():
    """I2: two graphs dirtied together enqueue only onto THEIR OWN pending."""
    g1 = DependencyGraph()
    g2 = DependencyGraph()
    g1.add_effect("e1", lambda: None, ["x"])
    g2.add_effect("e2", lambda: None, ["x"])
    e1 = g1.nodes["e1"]
    e2 = g2.nodes["e2"]
    e1.mark_stale()
    e2.mark_stale()
    assert list(g1._pending) == [e1]
    assert list(g2._pending) == [e2]
    assert e1 not in g2._pending and e2 not in g1._pending


def test_wake_list_lists_dirty_graphs_not_effects():
    """I2/I6: the only module-global scheduler state is the ordered GRAPH
    wake-list (coarse), never per-effect state."""
    g1 = DependencyGraph()
    g2 = DependencyGraph()
    g1.add_effect("e1", lambda: None, ["x"])
    g2.add_effect("e2", lambda: None, ["x"])
    g1.nodes["e1"].mark_stale()
    g2.nodes["e2"].mark_stale()
    assert set(_wake_list.values()) == {g1, g2}


def test_scope_destroy_drops_its_own_pending():
    """I2: scope teardown removes its own pending effects (and wakes), without
    touching any other graph's pending work."""
    graph = DependencyGraph()
    other = DependencyGraph()
    scope = ReactiveScope()
    scope.add_effect(graph, "e", lambda: None, ["x"])
    graph.nodes["e"].mark_stale()
    other.add_effect("o", lambda: None, ["x"])
    other.nodes["o"].mark_stale()
    assert graph._pending and other._pending
    scope.destroy()
    assert not graph._pending
    assert other._pending  # unaffected
    assert graph not in _wake_list.values()


# ─────────────────────────────────────────────────────────────
# P2 — deterministic per-graph ordering (I1) — landed green guard
# ─────────────────────────────────────────────────────────────

def test_older_graph_effects_precede_newer_graph_effects():
    """P2 / I1 (order policy): when one trigger dirties effects on a parent
    (older) graph and a child (newer) graph, every parent effect must run
    before every child effect — in EVERY fresh interpreter process."""
    outs = _run_many(_scenario(graphs=2, n=12))
    assert all(_blocks_are_ordered(o, 2) for o in outs), (
        "newer-graph effects ran before older-graph effects.\n"
        + "\n".join(outs[:3])
    )


def test_store_effects_precede_consumer_effects():
    """P2 / I1 (order policy): store graph effects precede component-consumer
    effects across three graphs (store → consumer A → consumer B)."""
    outs = _run_many(_scenario(graphs=3, n=8))
    assert all(_blocks_are_ordered(o, 3) for o in outs), (
        "consumer effects ran before store effects.\n"
        + "\n".join(outs[:3])
    )


# ─────────────────────────────────────────────────────────────
# P3 — batch & flush boundaries (I7) — unit scenarios, no SSR DOM
# ─────────────────────────────────────────────────────────────

def test_batch_holds_flushes_until_exit():
    """I7/I4: mutations inside batch() do not run effects until the block exits;
    the single exit flush reads the FINAL state (never a partial snapshot)."""
    obj = ReactiveObject()
    obj.x = 0
    obj.y = 0
    seen = []
    obj._dag.add_effect("e", lambda: seen.append((obj.x, obj.y)), ["x", "y"])
    with batch():
        obj.x = 1  # trigger would flush — held
        obj.y = 2
        assert seen == []  # nothing ran inside the batch
    assert seen == [(1, 2)]


def test_batch_discard_drops_pending_but_effect_stays_live():
    """I7: discard() drops pending effects WITHOUT running them AND resets their
    stale flag, so a genuine post-batch mutation still runs the effect (the
    dropped effect is not wedged clean/never-again)."""
    obj = ReactiveObject()
    obj.x = 0
    runs = []
    obj._dag.add_effect("e", lambda: runs.append(obj.x), ["x"])
    with batch() as b:
        obj.x = 1
        b.discard()
    assert runs == []  # pre-adoption work discarded, not applied
    obj.x = 2  # genuine post-adoption change
    assert runs == [2]


def test_scope_pending_count_and_discard_pending():
    """I2/I7: a scope can count and drop ONLY its own pending effects; the
    dropped effect stays live for a future real change."""
    graph = DependencyGraph()
    other = DependencyGraph()
    scope = ReactiveScope()
    runs = []
    scope.add_effect(graph, "e", lambda: runs.append(1), ["x"])
    graph.nodes["e"].mark_stale()
    other.add_effect("o", lambda: None, ["x"])
    other.nodes["o"].mark_stale()

    assert scope.pending_count() == 1
    assert scope.has_pending()
    dropped = scope.discard_pending()
    assert dropped == 1
    assert scope.pending_count() == 0
    assert not scope.has_pending()
    assert graph not in _wake_list.values()
    assert list(other._pending)  # untouched

    graph.trigger("x")  # a real change re-runs the (cleaned) effect
    assert runs == [1]


def test_nested_batches_drain_only_at_outermost_exit():
    """I7/I8: nested batches hold until the OUTERMOST exit; the inner exit does
    not flush early, and the single outer flush reads the final state."""
    obj = ReactiveObject()
    obj.x = 0
    runs = []
    obj._dag.add_effect("e", lambda: runs.append(obj.x), ["x"])
    with batch():
        obj.x = 1
        with batch():
            obj.x = 2
            assert runs == []  # inner exit does not flush
        assert runs == []  # outer batch still holds
    assert runs == [2]  # one flush at the outermost exit, final state


# ─────────────────────────────────────────────────────────────
# GREEN guards — must hold today and after each phase
# ─────────────────────────────────────────────────────────────

def test_cross_graph_trigger_wakes_effect_on_other_graph():
    """I6: triggering a state node on one graph runs an effect registered on a
    different graph (real cross-object edge, no relay)."""
    owner = ReactiveObject()
    owner.x = 1
    consumer = DependencyGraph()
    log = []
    consumer.add_effect("e", lambda: log.append(owner.x), [])
    consumer.nodes["e"].add_dependency(owner._dag.nodes["x"])
    owner.x = 2
    assert log == [2]


def test_trigger_flushes_synchronously():
    """I8: outside an explicit batch, a trigger flushes promptly — no deferral,
    no event loop required (the engine must keep working on the plain-Python
    SSR server too)."""
    obj = ReactiveObject()
    obj.x = 1
    log = []
    obj._dag.add_effect("e", lambda: log.append(obj.x), ["x"])
    obj.x = 5
    assert log == [5]  # already flushed by the time the setter returns


def test_single_trigger_runs_effect_once():
    """I3 (baseline): one trigger of one dependency runs the effect exactly
    once."""
    obj = ReactiveObject()
    obj.x = 1
    runs = []
    obj._dag.add_effect("e", lambda: runs.append(1), ["x"])
    obj.x = 2
    assert len(runs) == 1


def test_refrain_batch_flushes_once_with_final_state():
    """I4/I5/I8: the existing `refrain()` batch applies all mutations then
    flushes ONCE, so an effect depending on several fields reads the FINAL
    state — never a partial snapshot."""
    obj = ReactiveObject()
    obj.x = 0
    obj.y = 0
    seen = []
    obj._dag.add_effect("e", lambda: seen.append((obj.x, obj.y)), ["x", "y"])
    with obj.refrain() as r:
        r.x = 1
        r.y = 2
    assert seen == [(1, 2)]


def test_mid_drain_redirty_requeues_to_quiescence():
    """I5 (no lost update): an effect that is re-dirtied while the flush is
    already running is re-run in the same drain (a later wave), so a downstream
    effect never keeps a stale value."""
    obj = ReactiveObject()
    obj.x = 0
    obj.y = 0
    log = []
    obj._dag.add_effect("compute", lambda: setattr(obj, "y", obj.x + 1), ["x"])
    obj._dag.add_effect("render", lambda: log.append(obj.y), ["y"])
    obj.x = 1
    assert log == [2]


def test_prop_sync_child_style_converges_to_forwarded_value():
    """I4/I5 — documents the boundary of what the PURE scheduler guarantees.
    Even with the losing order (child 'style' effect reads the un-converged
    default first), quiescence re-runs it after the parent prop-sync, so the
    FINAL write is the forwarded value. (The real bug needs the DOM re-point
    dimension — see HYDRATION-REPOINT-RACE-FIX-PLAN.md §2.4 — where that
    corrective re-run can target the shadow node instead of the live SSR node;
    that is I7, fixed by the P3/P4 batch boundary.)"""
    parent = ReactiveObject()
    parent.direction = "row"
    child = ReactiveObject()
    child.direction = "column"  # the Stack class default
    writes = []
    parent._dag.add_effect(
        "prop_sync", lambda: setattr(child, "direction", parent.direction), ["direction"]
    )
    child._dag.add_effect("style", lambda: writes.append(child.direction), ["direction"])

    # Losing order on purpose: child style runs first (reads the default)…
    child._dag.trigger("direction")
    # …then the parent prop-sync converges the child, which re-runs the style.
    parent._dag.trigger("direction")

    assert writes == ["column", "row"]
    assert writes[-1] == "row"
