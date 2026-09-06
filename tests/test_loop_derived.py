"""
P4c — per-loop-item @derived (REACTIVITY-OVERHAUL.md P4c).

A @derived method is a reactive FUNCTION (vs @computed's reactive property):
the loop body builder instantiates one memoized ComputedNode per derived × per
loop item on the item's mini-DAG. Values are computed from the item + owner
state; they recompute when owner/store state changes (execution-tracked
cross-object edges, P3) or when a stable key is reused with a new item value;
and they are torn down when the item is removed.
"""
import pytest

from basis.shared.base_component import BaseComponent
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.reactive import (
    ComputedNode,
    EffectNode,
    _wake_list,
    derived,
)
from basis.shared.store import Store


@pytest.fixture(autouse=True)
def _clean_state():
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    _wake_list.clear()
    yield
    _wake_list.clear()


def _mount(cls, **attrs):
    return cls.mount(Element("div", attrs={}, children=[]), **attrs)


def _loop(owner):
    return next(b for b in owner.__bindings__ if hasattr(b, "instances"))


def _text_of(node):
    if node is None:
        return None
    return getattr(node, "textContent", None) or "".join(
        _text_of(c) for c in getattr(node, "children", [])
    )


def test_derived_renders_in_loop_body():
    """A @derived value referenced by name in a loop body renders per item."""
    class Owner(Component):
        items = []

        @derived
        def full_name(self, it):
            return f"{it['first']} {it['last']}"

        def template(self):
            """
            <div>
                <div for="it" in="{items}">
                    <span>{full_name}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.items = [{"first": "Ada", "last": "Lovelace"},
                     {"first": "Grace", "last": "Hopper"}]
    text = _text_of(mounted.__element__)
    assert "Ada Lovelace" in text
    assert "Grace Hopper" in text
    assert "[Error:" not in text


def test_derived_is_memoized_per_item():
    """Each item's derived node computes once and memoizes until invalidated."""
    calls = []

    class Owner(Component):
        items = []

        @derived
        def label(self, it):
            calls.append(it["n"])
            return it["n"]

        def template(self):
            """
            <div>
                <div for="it" in="{items}">
                    <span>{label}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.items = [{"n": 1}, {"n": 2}]
    assert calls == [1, 2]  # computed once each on first render

    # Re-render without any state change → memo hit, no recompute.
    for entry in _loop(mounted).instances.values():
        entry.render()
    assert calls == [1, 2]


def test_owner_state_change_recomputes_derived():
    """THE contract: a derived reading owner state recomputes when that owner
    state changes, and the DOM binding showing it updates end-to-end (owner →
    per-item node → binding effect → DOM)."""
    class Owner(Component):
        items = []
        show_rank = False

        @derived
        def label(self, it):
            return f"{it['name']} #{it['rank']}" if self.show_rank else it["name"]

        def template(self):
            """
            <div>
                <div for="it" in="{items}">
                    <span>{label}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.items = [{"name": "Ada", "rank": 1}]
    assert "Ada" in _text_of(mounted.__element__)
    assert "#1" not in _text_of(mounted.__element__)

    mounted.show_rank = True
    assert "Ada #1" in _text_of(mounted.__element__)


def test_derived_reads_store_state():
    """A derived reading a STORE recomputes when the store changes — a real
    cross-object edge (execution tracking) delivered through the global flush."""
    store = Store("derived_store")
    store.rate = 10

    class Owner(Component):
        items = []

        @derived
        def total(self, it):
            return it["qty"] * store.rate

        def template(self):
            """
            <div>
                <div for="it" in="{items}">
                    <span>{total}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.items = [{"qty": 3}]
    assert "30" in _text_of(mounted.__element__)

    store.rate = 5
    assert "15" in _text_of(mounted.__element__)


def test_item_reuse_recomputes_derived():
    """A stable key reused with a NEW item value recomputes the derived (the
    item's deps haven't changed — its input key has — so the memo is
    invalidated explicitly on reuse)."""
    class Owner(Component):
        items = []

        @derived
        def doubled(self, it):
            return it["n"] * 2

        def template(self):
            """
            <div>
                <div for="it" in="{items}" key="id">
                    <span>{doubled}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.items = [{"id": 1, "n": 5}]
    loop = _loop(mounted)
    entry = loop.instances[1]
    assert "10" in _text_of(mounted.__element__)

    mounted.items = [{"id": 1, "n": 7}]  # same key, new value
    assert loop.instances[1] is entry     # reused, not rebuilt
    assert "14" in _text_of(mounted.__element__)


def test_per_item_derived_nodes_are_independent():
    """Each item owns its own derived ComputedNode; reusing item A's key does
    not touch item B's memo."""
    class Owner(Component):
        items = []

        @derived
        def scaled(self, it):
            return it["n"] * self.multiplier

        multiplier = 1

        def template(self):
            """
            <div>
                <div for="it" in="{items}" key="id">
                    <span>{scaled}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.items = [{"id": 1, "n": 10}, {"id": 2, "n": 20}]
    loop = _loop(mounted)
    node1 = loop.instances[1]._dag.nodes["scaled"]
    node2 = loop.instances[2]._dag.nodes["scaled"]
    assert isinstance(node1, ComputedNode)
    assert node1 is not node2
    assert node1.value == 10
    assert node2.value == 20

    # Reuse item 1 only.
    mounted.items = [{"id": 1, "n": 3}, {"id": 2, "n": 20}]
    assert node1.value == 3   # recomputed on reuse
    assert node2.value == 20  # untouched


def test_nested_loop_derived_binds_to_innermost_level():
    """@derived is a reactive function of the loop variable at the scope where
    it's evaluated: every loop level registers the derived keyed to its OWN
    item, and the innermost level wins (standard scoping — inner shadows outer,
    like Svelte/Vue)."""
    class Owner(Component):
        groups = []

        @derived
        def group_label(self, it):
            return f"[{it['name']}]"

        def template(self):
            """
            <div>
                <div for="g" in="{groups}">
                    <span>{group_label}</span>
                    <div for="m" in="{g['members']}">
                        <span>{m['name']}{group_label}</span>
                    </div>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.groups = [{"name": "A", "members": [{"name": "x"}, {"name": "y"}]}]
    text = _text_of(mounted.__element__)
    # Outer body: {group_label} applies to the outer item g.
    assert "[A]" in text
    # Inner body: {group_label} applies to the inner item m (innermost scope).
    assert "x[x]" in text and "y[y]" in text


def test_removing_item_disposes_derived_and_effect():
    """Removing an item tears down its derived node and detaches the owner
    effect's cross-graph edge (no dangling references)."""
    class Owner(Component):
        items = []

        @derived
        def doubled(self, it):
            return it["n"] * 2

        def template(self):
            """
            <div>
                <div for="it" in="{items}" key="id">
                    <span>{doubled}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.items = [{"id": 1, "n": 5}, {"id": 2, "n": 6}]
    loop = _loop(mounted)
    entry1 = loop.instances[1]
    derived_node = entry1._dag.nodes["doubled"]

    effect_nodes = [n for n in mounted._dag.nodes.values()
                    if isinstance(n, EffectNode)]
    assert any(derived_node in e.dependencies for e in effect_nodes)

    mounted.items = [{"id": 2, "n": 6}]  # remove item 1
    assert 1 not in loop.instances
    assert "doubled" not in entry1._dag.nodes
    effect_nodes = [n for n in mounted._dag.nodes.values()
                    if isinstance(n, EffectNode)]
    assert not any(derived_node in e.dependencies for e in effect_nodes)


def test_removing_all_items_clears_item_effects():
    """After clearing the collection, no per-item body effect remains on the
    owner DAG and no item's derived node is wired into it."""
    class Owner(Component):
        items = []

        @derived
        def doubled(self, it):
            return it["n"] * 2

        def template(self):
            """
            <div>
                <div for="it" in="{items}" key="id">
                    <span>{doubled}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    mounted.items = [{"id": 1, "n": 5}, {"id": 2, "n": 6}]
    loop = _loop(mounted)
    derived_nodes = [e._dag.nodes["doubled"] for e in loop.instances.values()]
    assert any(n.startswith("loop_effect_") for n in mounted._dag.nodes)

    mounted.items = []
    assert loop.instances == {}
    assert not any(n.startswith("loop_effect_") for n in mounted._dag.nodes)
    effect_nodes = [n for n in mounted._dag.nodes.values()
                    if isinstance(n, EffectNode)]
    for dn in derived_nodes:
        assert not any(dn in e.dependencies for e in effect_nodes)


def test_ssr_renders_derived():
    """SSR parity: the server render (same mount machinery) produces the same
    derived text — no hydration mismatch on the derived value."""
    from fastapi.testclient import TestClient

    from basis.server.app import Basis

    app = Basis()

    @app.page
    class Team(Component):
        members = [{"first": "Ada", "last": "Lovelace"}]

        @derived
        def full_name(self, it):
            return f"{it['first']} {it['last']}"

        def template(self):
            """
            <div>
                <div for="m" in="{members}">
                    <span>{full_name}</span>
                </div>
            </div>
            """

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Ada Lovelace" in resp.text
    assert "[Error:" not in resp.text
