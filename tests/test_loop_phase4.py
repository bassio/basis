"""
Collection-as-expression, scalar keys, nested scopes, stores.

Locks in the loop-scope behaviour that test_loop_scope_contract.py checks for
rendering:
  - `in=` is a real expression against owner + enclosing scopes
  - scalar (non-dict) items get distinct keys from the item itself
  - nested loops chain the outer item's scope
  - the loop's DAG deps are the real owner fields of the collection expression
"""

from basis.shared.component import Component
from basis.shared.reactive import computed
from basis.shared.element import Element
from basis.shared.store import Store


def text_of(node):
    if node is None:
        return None
    return getattr(node, "textContent", None) or "".join(
        text_of(c) for c in getattr(node, "children", [])
    )


def _loop(owner):
    return next(b for b in owner.__bindings__ if hasattr(b, "instances"))


def test_loop_collection_deps_trigger():
    """A collection whose dependencies change re-runs the loop — the DAG dep is
    the REAL owner field (`data`), not the raw expression string
    (`data['list']`), so the owner update actually fires the loop."""
    class Owner(Component):
        data = {"list": []}

        def template(self):
            """
            <div>
                <div for="it" in="{data['list']}" key="name">{it['name']}</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    loop = _loop(mounted)
    assert loop.instances == {}

    mounted.data = {"list": [{"name": "x"}, {"name": "y"}]}

    text = text_of(mounted.__element__)
    assert "x" in text and "y" in text
    assert set(loop.instances.keys()) == {"x", "y"}


def test_loop_scalar_key_stable():
    """Scalar items are keyed by the item itself; appending creates ONLY the new
    item — existing keys stay stable (no None-collapse, no full rebuild)."""
    class Owner(Component):
        years = []

        def template(self):
            """
            <div>
                <option for="y" in="{years}" key="y" value="{y}">{y}</option>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.years = [2020, 2021]
    loop = _loop(mounted)
    assert set(loop.instances.keys()) == {2020, 2021}
    first = loop.instances[2020]

    mounted.years = [2020, 2021, 2022]

    assert set(loop.instances.keys()) == {2020, 2021, 2022}
    # Existing keys are REUSED, not rebuilt.
    assert loop.instances[2020] is first
    text = text_of(mounted.__element__)
    assert "2022" in text


def test_loop_shadowing():
    """A loop variable shadows an owner attribute of the same name (Vue rule)."""
    class Owner(Component):
        items = []
        d = "owner-value"

        def template(self):
            """
            <div>
                <div for="d" in="{items}" key="id">{d['val']}</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"id": 1, "val": "shadow-1"}, {"id": 2, "val": "shadow-2"}]

    text = text_of(mounted.__element__)
    assert "shadow-1" in text and "shadow-2" in text
    assert "owner-value" not in text


def test_loop_store_collection():
    """`in=\"{$store.list}\"` — a store-backed collection renders (3.5).

    The DSL `$name.attr` means the store registered under *name*; here the
    store is `phase4_store_list`, so the expression is `$phase4_store_list.list`."""
    store = Store("phase4_store_list")
    store.list = [{"name": "x"}, {"name": "y"}]

    class Owner(Component):
        def template(self):
            """
            <div>
                <div for="it" in="{$phase4_store_list.list}" key="name">{it['name']}</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    text = text_of(mounted.__element__)
    assert "x" in text and "y" in text
    assert "[Error:" not in text
