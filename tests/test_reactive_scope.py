"""
P4a — the ReactiveScope primitive + DependencyGraph.remove_node + a root scope
on every ReactiveObject (REACTIVITY-OVERHAUL.md P4a).

GREEN immediately: P4a adds the primitive and a root scope but changes no
existing behavior. P4b (loop/region/HMR/subscription adoption) and P4c
(per-loop-item derived) build on it.
"""
import pytest

from basis.shared.base_component import BaseComponent
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.reactive import (
    ComputedNode,
    DependencyGraph,
    ReactiveObject,
    ReactiveScope,
    _dirty_effects,
)
from basis.shared.store import Store


@pytest.fixture(autouse=True)
def _clean_state():
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    _dirty_effects.clear()
    yield
    _dirty_effects.clear()


def _mount(cls, **attrs):
    return cls.mount(Element("div", attrs={}, children=[]), **attrs)


# ─────────────────────────────────────────────
# ReactiveScope primitive
# ─────────────────────────────────────────────

def test_scope_add_effect_and_destroy():
    graph = DependencyGraph()
    scope = ReactiveScope()
    scope.add_effect(graph, "e1", lambda: None, ["x"])
    assert "e1" in graph.nodes
    scope.destroy()
    assert "e1" not in graph.nodes


def test_scope_add_computed_and_destroy():
    graph = DependencyGraph()
    scope = ReactiveScope()
    obj = ReactiveObject()
    scope.add_computed(graph, "c1", lambda o: getattr(o, "x", 0), obj, ["x"])
    assert "c1" in graph.nodes
    assert isinstance(graph.nodes["c1"], ComputedNode)
    scope.destroy()
    assert "c1" not in graph.nodes


def test_scope_children_destroy_recursively():
    graph = DependencyGraph()
    root = ReactiveScope()
    child = root.child()
    grandchild = child.child()
    child.add_effect(graph, "e1", lambda: None, ["x"])
    grandchild.add_effect(graph, "e2", lambda: None, ["x"])
    root.destroy()
    assert "e1" not in graph.nodes
    assert "e2" not in graph.nodes
    assert root.children == []


def test_scope_child_destroy_detaches_from_parent():
    root = ReactiveScope()
    child = root.child()
    assert child in root.children
    child.destroy()
    assert child not in root.children


def test_scope_destroy_is_idempotent():
    graph = DependencyGraph()
    scope = ReactiveScope()
    scope.add_effect(graph, "e1", lambda: None, ["x"])
    scope.destroy()
    scope.destroy()  # no error
    assert "e1" not in graph.nodes


def test_scope_add_effect_runs_on_owner_graph():
    """The scope records (graph, name) — the effect runs on the owner's DAG."""
    graph = DependencyGraph()
    scope = ReactiveScope()
    scope.add_effect(graph, "e", lambda: None, ["x"])
    assert graph.nodes["e"] in graph.effects


# ─────────────────────────────────────────────
# DependencyGraph.remove_node
# ─────────────────────────────────────────────

def test_remove_node_state_detaches_dependents():
    graph = DependencyGraph()
    graph.get_or_create_state("x")
    graph.add_effect("e", lambda: None, ["x"])
    x_node = graph.nodes["x"]
    e_node = graph.nodes["e"]
    assert x_node in e_node.dependencies
    graph.remove_node("x")
    assert "x" not in graph.nodes
    assert x_node not in e_node.dependencies  # detached, not dangling


def test_remove_node_computed_detaches_from_its_deps():
    graph = DependencyGraph()
    obj = ReactiveObject()
    graph.add_computed("c", lambda o: getattr(o, "x", 0), obj, ["x"])
    x_node = graph.nodes["x"]
    c_node = graph.nodes["c"]
    assert x_node in c_node.dependencies
    assert c_node in x_node.dependents
    graph.remove_node("c")
    assert "c" not in graph.nodes
    assert c_node not in x_node.dependents
    assert "x" in graph.nodes  # the state node remains


def test_remove_node_discards_from_dirty_effects():
    graph = DependencyGraph()
    graph.add_effect("e", lambda: None, ["x"])
    node = graph.nodes["e"]
    _dirty_effects.add(node)
    graph.remove_node("e")
    assert node not in _dirty_effects


def test_remove_node_missing_is_noop():
    graph = DependencyGraph()
    graph.remove_node("does_not_exist")  # no error


# ─────────────────────────────────────────────
# Root scope on every ReactiveObject
# ─────────────────────────────────────────────

def test_every_reactive_object_has_root_scope():
    obj = ReactiveObject()
    assert isinstance(obj._scope, ReactiveScope)
    assert obj._scope.parent is None


def test_store_has_root_scope():
    store = Store("scoped")
    assert isinstance(store._scope, ReactiveScope)


def test_mounted_component_has_root_scope():
    class C(Component):
        __tag__ = "x-scope-root"
        count = 0

        def template(self):
            """<div><span>{count}</span></div>"""

    comp = _mount(C)
    assert isinstance(comp._scope, ReactiveScope)


# ─────────────────────────────────────────────
# P4b — scope adoption (loop / bindings / subscriptions / HMR)
# ─────────────────────────────────────────────

def test_loop_item_effects_are_scoped_and_dispose_cleans_them():
    class Owner(Component):
        __tag__ = "x-p4b-loop"
        items = [{"n": 1, "k": "a"}]
        mode = "light"

        def template(self):
            """
            <div>
                <div for="it" in="{items}" key="k" class="{mode}">{it['n']}</div>
            </div>
            """

    mounted = _mount(Owner)
    lb = next(b for b in mounted.__bindings__ if b.__class__.__name__ == "LoopBinding")
    entry = next(iter(lb.instances.values()))
    # The body binding's owner-effect is owned by the item's sub-scope.
    assert entry._subscope._effects, "item scope should own at least one effect"
    effect_name = entry._subscope._effects[0][1]
    assert effect_name in mounted._dag.nodes
    entry.dispose()
    assert effect_name not in mounted._dag.nodes  # scoped teardown, no dag arg


def test_binding_effects_are_scoped():
    class C(Component):
        __tag__ = "x-p4b-binding"
        count = 0

        def template(self):
            """<div><span>{count}</span></div>"""

    comp = _mount(C)
    effect_names = [name for _, name in comp._scope._effects]
    assert len(effect_names) >= 1
    comp._scope.destroy()
    for name in effect_names:
        assert name not in comp._dag.nodes


def test_store_subscription_is_scoped_to_subscriber():
    store = Store("scoped_store")

    class Sub(Component):
        __tag__ = "x-p4b-sub"

        def template(self):
            """<div><span>{$scoped_store.value}</span></div>"""

    sub = _mount(Sub)
    sub_effect_names = [name for _, name in sub._scope._effects]
    assert any(name.startswith("sub_") for name in sub_effect_names)
    before = len(store._dag.effects)
    sub._scope.destroy()
    assert len(store._dag.effects) < before  # subscription edge removed from the store


def test_rerender_after_swap_resets_scope():
    class C(Component):
        __tag__ = "x-p4b-hmr"
        count = 0

        def template(self):
            """<div><span>{count}</span></div>"""

    comp = _mount(C)
    old_scope = comp._scope
    comp._rerender_after_swap({})
    assert comp._scope is not old_scope
    assert isinstance(comp._scope, ReactiveScope)
