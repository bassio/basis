"""
P1 — additive reactive read-tracking plumbing (REACTIVITY-OVERHAUL.md).

These tests exercise the new execution-tracking machinery directly
(``ReactiveObject._tracked_reads`` + read-recording in ``__getattribute__``,
the ``_track`` context manager and ``_TrackingProbe``). They are GREEN
immediately: P1 must not change any existing behavior — the overhaul contract
tests in ``test_computed_overhaul_contract.py`` stay RED until P2/P3 switch
computed invalidation over to the tracked dependencies.
"""
import pytest

from basis.shared.base_component import BaseComponent
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.reactive import ReactiveObject, computed, _track, _tracker_stack, _TrackingProbe
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
# Basic read recording
# ─────────────────────────────────────────────────────────────

def test_tracks_plain_state_read():
    class C(Component):
        __tag__ = "x-track-1"
        count = 0

        def template(self):
            """<div><span>{count}</span></div>"""

    comp = _mount(C)
    deps = comp._tracked_reads(lambda self: self.count)
    assert deps == {comp._dag.nodes["count"]}


def test_tracks_computed_read_as_its_node():
    class C(Component):
        __tag__ = "x-track-2"
        count = 1

        def template(self):
            """<div><span>{d}</span></div>"""

        @computed
        def d(self):
            return self.count * 2

    comp = _mount(C)
    deps = comp._tracked_reads(lambda self: self.d)
    assert comp._dag.nodes["d"] in deps


def test_tracks_through_helper_method():
    class C(Component):
        __tag__ = "x-track-3"
        base = 10

        def template(self):
            """<div><span>{base}</span></div>"""  # registers 'base' as a state node

        def _triple(self):
            return self.base * 3

        @computed
        def h(self):
            return self._triple()

    comp = _mount(C)
    # The helper's read of self.base is inside the tracking context.
    deps = comp._tracked_reads(lambda self: self._triple())
    assert comp._dag.nodes["base"] in deps


def test_tracks_getattr_read():
    class C(Component):
        __tag__ = "x-track-4"
        x = 1

        def template(self):
            """<div><span>{x}</span></div>"""

    comp = _mount(C)
    deps = comp._tracked_reads(lambda self: getattr(self, "x"))
    assert comp._dag.nodes["x"] in deps


def test_tracks_dotted_chain_base_attr():
    class Profile:
        def __init__(self, first):
            self.first = first

    class C(Component):
        __tag__ = "x-track-5"
        profile = Profile("Ann")

        def template(self):
            """<div><span>{fn}</span></div>"""

        @computed
        def fn(self):
            return self.profile.first

    comp = _mount(C)
    # Only the reactive base attr has a node; the nested .first is plain data.
    deps = comp._tracked_reads(lambda self: self.profile.first)
    assert deps == {comp._dag.nodes["profile"]}


# ─────────────────────────────────────────────────────────────
# Cross-object tracking (the P3 foundation)
# ─────────────────────────────────────────────────────────────

def test_tracks_cross_store_read_as_producer_node():
    """Reading self.S['cart'].count records the STORE's 'count' node — the
    first-class cross-object edge, discovered without any string relay."""
    cart = Store("cart")
    cart.count = 0

    class C(Component):
        __tag__ = "x-track-6"
        count = 0

        def template(self):
            """<div><span>{n}</span></div>"""

    comp = _mount(C)
    deps = comp._tracked_reads(lambda self: self.S["cart"].count)
    # The producer's node is recorded (plus any on-demand-promoted read such as
    # the 'S' registry access).
    assert cart._dag.nodes["count"] in deps


def test_tracks_store_read_on_a_store():
    """A Store's body can read another Store; the read is recorded against the
    producer's node (the P3 'store→store computed' foundation)."""
    class A(Store):
        count = 0

    a = A("a")
    a.count = 0  # registers the producer's 'count' state node

    class B(Store):
        pass

    b = B("b")
    deps = b._tracked_reads(lambda self: Store._registry["a"].count)
    assert deps == {a._dag.nodes["count"]}


# ─────────────────────────────────────────────────────────────
# Tracking discipline
# ─────────────────────────────────────────────────────────────

def test_ignores_private_and_dunder_reads():
    class C(Component):
        __tag__ = "x-track-7"
        count = 0
        _secret = 42

        def template(self):
            """<div><span>{count}</span></div>"""

    comp = _mount(C)
    deps = comp._tracked_reads(
        lambda self: (self.count, self._secret, self._dag, self.__class__)
    )
    assert deps == {comp._dag.nodes["count"]}


def test_no_overhead_path_when_idle():
    class C(Component):
        __tag__ = "x-track-8"
        count = 0

        def template(self):
            """<div><span>{count}</span></div>"""

    comp = _mount(C)
    assert _tracker_stack == []
    assert comp.count == 0  # plain reads work and record nothing
    assert comp.__dict__["count"] == 0
    assert _tracker_stack == []  # nothing pushed


def test_nested_tracking_isolation():
    class C(Component):
        __tag__ = "x-track-9"
        a = 1
        b = 2

        def template(self):
            """<div><span>{a}{b}</span></div>"""

    comp = _mount(C)
    outer = _TrackingProbe()
    inner = _TrackingProbe()
    with _track(outer):
        with _track(inner):
            _ = comp.b
        _ = comp.a
    assert inner.dependencies == {comp._dag.nodes["b"]}
    assert outer.dependencies == {comp._dag.nodes["a"]}


def test_probe_does_not_mutate_dep_dependents():
    """The P1 probe records into itself only — no spurious dependents edges."""
    class C(Component):
        __tag__ = "x-track-10"
        count = 0

        def template(self):
            """<div><span>{count}</span></div>"""

    comp = _mount(C)
    before = set(comp._dag.nodes["count"].dependents)
    comp._tracked_reads(lambda self: self.count)
    assert set(comp._dag.nodes["count"].dependents) == before


def test_works_on_plain_reactive_object():
    obj = ReactiveObject()
    obj.x = 5
    deps = obj._tracked_reads(lambda self: self.x + 1)
    assert deps == {obj._dag.nodes["x"]}


# ─────────────────────────────────────────────────────────────
# P2 — @computed on execution tracking (lazy + tracked deps)
# ─────────────────────────────────────────────────────────────

def test_computed_is_lazy_until_first_access():
    class M(Store):
        x = 1

        def __init__(self, name):
            super().__init__(name)
            self.__dict__["_calls"] = 0

        @computed
        def d(self):
            self.__dict__["_calls"] += 1
            return self.x * 2

    store = M("m")
    assert store.__dict__["_calls"] == 0  # not computed at construction
    assert store.d == 2
    assert store.__dict__["_calls"] == 1


def test_computed_tracks_class_attr_not_referenced_elsewhere():
    """A class-default attr read only inside the computed body is promoted to a
    StateNode on demand, so assigning it re-runs the computed (no AST dep)."""
    class C(Component):
        __tag__ = "x-p2-promote"
        base = 10

        def template(self):
            """<div><span>{h}</span></div>"""

        @computed
        def h(self):
            return self.base * 2

    comp = _mount(C)
    assert comp.h == 20
    comp.base = 5
    assert comp.h == 10


def test_circular_computed_raises_clear_error():
    class C(Component):
        __tag__ = "x-p2-cycle"

        def template(self):
            """<div></div>"""  # no binding reads d, so the cycle only triggers on access

        @computed
        def d(self):
            return self.d + 1

    comp = _mount(C)
    with pytest.raises(RecursionError):
        _ = comp.d


# ─────────────────────────────────────────────────────────────
# P3 — first-class cross-object edges
# ─────────────────────────────────────────────────────────────

def test_effect_on_one_object_runs_when_another_object_changes():
    """Cross-object effect processing: a change on the producer object flushes
    the consumer's effects too (no manual react()/subscription needed)."""
    store = Store("svc")
    store.count = 0

    class Panel(Component):
        __tag__ = "x-p3-effect"
        count = 0

        def template(self):
            """<div><span>{n}</span></div>"""

        @computed
        def n(self):
            return self.S["svc"].count

    panel = _mount(Panel)
    tb = next(b for b in panel.__bindings__ if b.__class__.__name__ == "TextBinding")
    assert tb.node.value == "0"
    store.count = 9
    assert tb.node.value == "9"


def test_component_registered_under_component_id_identity():
    """__component_id__ registers the component for #-references independent of
    the root element's id."""
    class T(Component):
        __tag__ = "x-p3-id"
        __component_id__ = "named"
        count = 0

        def template(self):
            """<div id="other"><span>{count}</span></div>"""

    t = _mount(T)
    from basis.shared.base_component import BaseComponent
    assert BaseComponent.C.get("named") is t


def test_subscription_relay_reacts_on_reference_name():
    """The #-subscription edge reacts on the subscriber's reference name, so a
    binding '{#tgt.count}' updates even when the target's DOM id differs."""
    class Target(Component):
        __tag__ = "x-p3-tgt"
        __component_id__ = "tgt"
        count = 0

        def template(self):
            """<div id="other"><span>{count}</span></div>"""

    class Sub(Component):
        __tag__ = "x-p3-sub"

        def template(self):
            """<div><span>{#tgt.count}</span></div>"""

    target = _mount(Target)
    subscriber = _mount(Sub)
    tb = next(b for b in subscriber.__bindings__ if b.__class__.__name__ == "TextBinding")
    assert tb.node.value == "0"
    target.count = 5
    assert tb.node.value == "5"


def test_identity_fallback_to_element_id():
    """Without __component_id__, a component registers under its root element's
    id (existing behavior preserved)."""
    class T(Component):
        __tag__ = "x-p3-fallback"
        count = 0

        def template(self):
            """<div id="legacy"><span>{count}</span></div>"""

    t = _mount(T)
    from basis.shared.base_component import BaseComponent
    assert BaseComponent.C.get("legacy") is t
