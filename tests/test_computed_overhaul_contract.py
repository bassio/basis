"""
Contract harness for the reactivity overhaul (REACTIVITY-OVERHAUL.md).

The RED tests encode the TARGET behavior of the overhaul (execution-tracked
computed dependencies + first-class cross-object edges). They are expected to
FAIL against the current AST-based implementation. Keep them RED until their
phase lands; do NOT edit them to match current behavior.

  P2 targets (execution tracking / lazy computed):
    test_computed_tracks_helper_method_reads
    test_computed_tracks_getattr_reads
    test_computed_tracks_in_place_nested_mutation
    test_lazy_computed_tolerates_missing_initial_attr
  P3 targets (real cross-object edges):
    test_cross_store_computed_auto_tracks
    test_store_computed_can_read_another_store
    test_cross_component_computed_resolves_by_identity_not_dom_id

The GREEN guards pin behaviors that MUST NOT regress while the overhaul lands
(manual ``$store.attr`` dependencies, memoization, same-object chaining).
"""
import pytest

from basis.shared.base_component import BaseComponent
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.reactive import ReactiveObject, computed
from basis.shared.store import Store


@pytest.fixture(autouse=True)
def _clean_registries():
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    yield


def _mount(cls, **attrs):
    return cls.mount(Element("div", attrs={}, children=[]), **attrs)


# ─────────────────────────────────────────────────────────────
# RED contracts — P2 (execution tracking / lazy computed)
# ─────────────────────────────────────────────────────────────

def test_computed_tracks_helper_method_reads():
    """P2: reads inside a helper method called from the computed body are
    tracked, so the computed re-runs when the helper's dependency changes."""
    class Helper(Component):
        __tag__ = "x-overhaul-helper"
        base = 10

        def template(self):
            """<div><span>{h}</span></div>"""

        def _triple(self):
            return self.base * 3

        @computed
        def h(self):
            return self._triple()

    comp = _mount(Helper)
    assert comp.h == 30
    comp.base = 20
    assert comp.h == 60  # RED today: deps=['_triple'] -> never re-runs, stays 30


def test_computed_tracks_getattr_reads():
    """P2: dynamic getattr(self, 'x') reads are tracked."""
    class G(Component):
        __tag__ = "x-overhaul-getattr"
        x = 1

        def template(self):
            """<div><span>{g}</span></div>"""

        @computed
        def g(self):
            return getattr(self, "x") * 2

    comp = _mount(G)
    assert comp.g == 2
    comp.x = 5
    assert comp.g == 10  # RED today: deps=[] -> stays 2


def test_computed_tracks_in_place_nested_mutation():
    """P2: a read of a nested REACTIVE object is tracked across objects, so
    mutating the nested field in place re-runs the computed. (Plain non-reactive
    nested objects are out of scope — deep proxy reactivity is an anti-goal.)"""
    class Profile(ReactiveObject):
        def __init__(self, first):
            super().__init__()
            self.first = first

    class P(Component):
        __tag__ = "x-overhaul-nested"
        profile = Profile("Ann")

        def template(self):
            """<div><span>{fn}</span></div>"""

        @computed
        def fn(self):
            return self.profile.first

    comp = _mount(P)
    assert comp.fn == "Ann"
    comp.profile.first = "Zoe"
    assert comp.fn == "Zoe"  # the nested REACTIVE object's node is the edge


def test_lazy_computed_tolerates_missing_initial_attr():
    """P2: a @computed reading an attribute with NO class default does not abort
    mounting; it resolves lazily and re-runs once the attribute is defined."""
    class L(Component):
        __tag__ = "x-overhaul-lazy"

        def template(self):
            """<div><span>{m}</span></div>"""

        @computed
        def m(self):
            return (self.missing or 0) * 2

    try:
        comp = _mount(L)
    except Exception as e:
        raise AssertionError(
            f"mount aborted by forced computed update: {type(e).__name__}: {e}"
        ) from e

    comp.missing = 21
    assert comp.m == 42  # RED today: 'missing' never tracked -> stays 0


# ─────────────────────────────────────────────────────────────
# RED contracts — P3 (first-class cross-object edges)
# ─────────────────────────────────────────────────────────────

def test_cross_store_computed_auto_tracks():
    """P3: a component @computed reading self.S['store'].attr re-runs when the
    store changes — WITHOUT manual dependencies=."""
    cart = Store("cart")
    cart.count = 0

    class Panel(Component):
        __tag__ = "x-overhaul-panel"
        count = 0

        def template(self):
            """<div><span>{n}</span></div>"""

        @computed
        def n(self):
            return self.S["cart"].count

    panel = _mount(Panel)
    assert panel.n == 0
    cart.count = 7
    assert panel.n == 7  # RED today: deps=['S'] never triggered -> stays 0


def test_store_computed_can_read_another_store():
    """P3: a Store @computed can derive from another Store and re-run."""
    class A(Store):
        count = 0

    a = A("a")

    class B(Store):
        @computed
        def doubled(self):
            return Store._registry["a"].count * 2

    b = B("b")
    assert b.doubled == 0
    a.count = 5
    assert b.doubled == 10  # RED today: deps=[] -> memoized forever at 0


def test_cross_component_computed_resolves_by_identity_not_dom_id():
    """P3: '#name.attr' resolves by registered component identity, not by
    matching the target element's HTML id."""
    class Target(Component):
        __tag__ = "x-overhaul-target"
        __component_id__ = "tgt"  # identity independent of the DOM id
        count = 0

        def template(self):
            """<div id="other"><span>{count}</span></div>"""

    class Sub(Component):
        __tag__ = "x-overhaul-sub"
        count = 0

        def template(self):
            """<div><span>{d}</span></div>"""

        @computed(dependencies=["#tgt.count"])
        def d(self):
            from basis.shared.base_component import BaseComponent
            tgt = BaseComponent.C.get("tgt")
            return getattr(tgt, "count", None) if tgt is not None else None

    target = _mount(Target)
    sub = _mount(Sub)
    target.count = 3
    assert sub.d == 3  # resolves by __component_id__ (not the DOM id 'other')


def test_cross_store_change_propagates_to_dom_binding():
    """P3: a store change propagates to a component DOM binding that reads a
    computed depending on the store — with no manual react()/subscription."""
    cart = Store("cart")
    cart.count = 0

    class Panel(Component):
        __tag__ = "x-overhaul-dom"
        count = 0

        def template(self):
            """<div><span>{n}</span></div>"""

        @computed
        def n(self):
            return self.S["cart"].count

    panel = _mount(Panel)
    tb = next(b for b in panel.__bindings__ if b.__class__.__name__ == "TextBinding")
    assert tb.node.value == "0"
    cart.count = 7
    assert tb.node.value == "7"  # RED before P3 (cross-object effect processing)


# ─────────────────────────────────────────────────────────────
# GREEN guards — must not regress while the overhaul lands
# ─────────────────────────────────────────────────────────────

def test_manual_cross_store_dependencies_still_honored():
    """The documented escape hatch keeps working: manual $store.attr deps on a
    component still re-run (via the subscription machinery)."""
    counter = Store("counter")
    counter.count = 0

    class Manual(Component):
        __tag__ = "x-overhaul-manual"
        count = 0

        def template(self):
            """<div><span>{m}</span></div>"""

        @computed(dependencies=["$counter.count"])
        def m(self):
            return self.S["counter"].count

    comp = _mount(Manual)
    assert comp.m == 0
    counter.count = 42
    assert comp.m == 42


def test_computed_memoizes_between_dependency_changes():
    """A computed is recomputed at most once per dependency change, and cached
    between changes. Robust to both the current eager init and the target lazy
    init (we reset the counter after construction)."""
    class M(Store):
        x = 1

        def __init__(self, name):
            self.__dict__["_calls"] = 0
            super().__init__(name)

        @computed
        def d(self):
            self.__dict__["_calls"] += 1
            return self.x * 2

    store = M("m")
    store.__dict__["_calls"] = 0  # ignore any init-time computation
    store.x = 2                    # force a recompute
    assert store.d == 4
    assert store.__dict__["_calls"] == 1
    assert store.d == 4  # cached — no recompute
    assert store.__dict__["_calls"] == 1
    store.x = 3
    assert store.d == 6
    assert store.__dict__["_calls"] == 2
    assert store.d == 6  # cached again
    assert store.__dict__["_calls"] == 2


def test_computed_chaining_auto_tracks_within_object():
    """Chained computed → computed within one object stays reactive."""
    class Chain(Store):
        a = 1

        @computed
        def b(self):
            return self.a * 2

        @computed
        def c(self):
            return self.b + 1

    store = Chain("chain")
    assert store.c == 3
    store.a = 10
    assert store.c == 21
