"""The loop engine (``shared/loop.py``): pure reconciliation diffing, body
construction, and the repoint delegate.

These are the DOM-free unit tests for the pieces ``LoopBinding`` is built from:

* ``Reconciler.diff`` produces the exact op plan for keyed/unkeyed reorders.
* ``derive_keys`` derives stable reconciliation keys.
* ``LoopBodyBuilder`` builds owner-bound, per-item ``LoopItem`` bodies and
  formats custom-element child props.
* ``LoopBinding.repoint_to_ssr`` delegates to
  ``hydration.repoint_loop_to_ssr`` (behavior is covered in
  ``test_loop_ssr_repoint.py``).
"""

from basis.shared.component import Component
from basis.shared.bindings import LoopItem
from basis.shared.element import Element
from basis.shared.hydration import repoint_loop_to_ssr
from basis.shared.loop import LoopBodyBuilder, Reconciler, derive_keys


def _loop(owner):
    return next(b for b in owner.__bindings__ if b.__class__.__name__ == "LoopBinding")


def _ops(old_keys, new_keys):
    return [(op.kind, op.key, op.index) for op in Reconciler.diff(old_keys, new_keys)]


# ---------------------------------------------------------------------------
# Reconciler.diff — pure op plans
# ---------------------------------------------------------------------------

def test_diff_noop():
    assert _ops([1, 2], [1, 2]) == [("update", 1, 0), ("update", 2, 1)]


def test_diff_remove_and_create():
    # 1 removed, 3 and 4 created, 2 reused in place.
    assert _ops([1, 2], [2, 3, 4]) == [
        ("remove", 1, -1),
        ("update", 2, 0),
        ("create", 3, 1),
        ("create", 4, 2),
    ]


def test_diff_full_swap_moves_one():
    # B and A swap: the LIS stable subsequence keeps one in place, the other moves.
    assert _ops(["A", "B"], ["B", "A"]) == [
        ("update", "B", 0),
        ("update", "A", 1),
        ("move", "B", 0),
    ]


def test_diff_clear_all():
    assert _ops([1, 2], []) == [("remove", 1, -1), ("remove", 2, -1)]


def test_diff_populate_all():
    assert _ops([], [1, 2]) == [("create", 1, 0), ("create", 2, 1)]


def test_diff_unkeyed_reuses_by_positional_index():
    # Unkeyed loops use positional indices, so every key always exists.
    assert _ops([0, 1, 2], [0, 1, 2]) == [
        ("update", 0, 0),
        ("update", 1, 1),
        ("update", 2, 2),
    ]


def test_diff_create_in_middle_then_reorder():
    ops = _ops(["A", "B"], ["C", "B", "A"])
    assert ("create", "C", 0) in ops
    # A is the LIS stable tail; B must move after it.
    assert ("move", "B", 1) in ops


def test_diff_remove_precedes_reorder():
    # Removals come first, then create/update, then moves.
    ops = _ops([1, 2, 3], [3, 4])
    kinds = [kind for kind, _, _ in ops]
    assert kinds.index("remove") < kinds.index("update") < kinds.index("create")


# ---------------------------------------------------------------------------
# derive_keys
# ---------------------------------------------------------------------------

def test_derive_keys_keyed():
    assert derive_keys([{"id": 1}, {"id": 2}], "id") == [1, 2]


def test_derive_keys_scalar_items_fall_back_to_self():
    assert derive_keys([10, 20], "y") == [10, 20]


def test_derive_keys_unhashable_falls_back_to_position():
    assert derive_keys([{"k": [1, 2]}, {"k": [3]}], "k") == [0, 1]


def test_derive_keys_unkeyed_is_positional():
    assert derive_keys(["a", "b"], None) == [0, 1]


# ---------------------------------------------------------------------------
# LoopBodyBuilder
# ---------------------------------------------------------------------------

class Owner(Component):
    items = []

    def template(self):
        """
        <div>
            <div for="it" in="{items}" key="k" class="item-{it['k']}">{it['name']}</div>
        </div>
        """


def _mounted_plain():
    m = Owner.mount(Element("div", attrs={}, children=[]))
    m.items = [{"k": 1, "name": "A"}]
    return m


def _builder(owner):
    lb = _loop(owner)
    return LoopBodyBuilder(lb.component_instance, lb.body_blueprints,
                           lb.item, lb.enclosing_scope, lb.clone)


def test_builder_builds_owner_bound_per_item_body():
    m = _mounted_plain()
    item = _builder(m).build({"k": 2, "name": "B"}, 2)
    assert isinstance(item, LoopItem)
    assert item.key == 2
    # Body bindings are bound to the owner.
    assert item.bindings and all(b.component_instance is m for b in item.bindings)
    # The per-item scope overlay carries the loop variable.
    assert item.scope.vars["it"] == {"k": 2, "name": "B"}
    assert item.scope.parent is None


def test_builder_child_props_formats_expressions():
    clone = Element("x-card", attrs={
        "for": "c", "in": "{cards}", "label": "{c['name']}", "fixed": "hi",
    }, children=[])
    builder = LoopBodyBuilder(component_instance=object(),
                              body_blueprints=[], item="c",
                              enclosing_scope=None, clone=clone)
    props = builder.child_props({"id": 2, "name": "B"})
    # Loop variable + formatted {expr} attrs; loop-control attrs excluded.
    assert props == {"c": {"id": 2, "name": "B"}, "label": "B", "fixed": "hi"}


def test_builder_child_props_non_custom_is_just_the_item():
    clone = Element("div", attrs={"for": "it", "in": "{items}"}, children=[])
    builder = LoopBodyBuilder(component_instance=object(),
                              body_blueprints=[], item="it",
                              enclosing_scope=None, clone=clone)
    assert builder.child_props({"x": 1}) == {"it": {"x": 1}}


# ---------------------------------------------------------------------------
# Repoint delegate
# ---------------------------------------------------------------------------

def test_repoint_to_ssr_delegates_to_hydration(monkeypatch):
    m = _mounted_plain()
    lb = _loop(m)
    calls = []

    def fake(binding, ssr_parent, report=None):
        calls.append((binding, ssr_parent))
        return ["attached"]

    monkeypatch.setattr("basis.shared.bindings.repoint_loop_to_ssr", fake)
    result = lb.repoint_to_ssr("PARENT", report=None)
    assert calls == [(lb, "PARENT")]
    assert result == ["attached"]


def test_repoint_helper_lives_in_hydration():
    # The re-pointer is owned by hydration.py (canonical-path tree matching).
    import basis.shared.hydration as hydration_mod
    assert hydration_mod.repoint_loop_to_ssr is repoint_loop_to_ssr
    assert hasattr(hydration_mod, "_find_ssr_item_by_key")
