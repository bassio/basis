"""
Loop-scope contract: parent fields read in a loop body stay live, scalar items
get distinct keys, and nested / subscripted collections render.  These lock
the loop-scope guarantees that test_loop_phase4.py exercises in more detail.
"""

from basis.shared.component import Component
from basis.shared.reactive import computed
from basis.shared.element import Element


def text_of(node):
    if node is None:
        return None
    return getattr(node, "textContent", None) or "".join(
        text_of(c) for c in getattr(node, "children", [])
    )


def _loop(owner):
    return next(b for b in owner.__bindings__
                if b.__class__.__name__ == "LoopBinding")


def _attr_binding(instance, attr):
    bindings = getattr(instance, "bindings", None)
    if bindings is None:
        bindings = getattr(instance, "__bindings__", [])
    for b in bindings:
        if b.__class__.__name__ == "AttributeBinding" and getattr(b, "attr", None) == attr:
            return b
    return None


# --------------------------------------------------------------------------
# A parent field read in a loop body stays live on in-place change.
# --------------------------------------------------------------------------
def test_loop_body_parent_field_stays_live():
    class Owner(Component):
        items = [{"n": 1, "k": "a"}, {"n": 2, "k": "b"}]
        mode = "light"

        @computed(dependencies=["items"])
        def visible(self):
            return self.items

        def template(self):
            """
            <div>
                <div for="it" in="{visible}" key="k" class="item {mode}">{it['n']}</div>
            </div>
            """

        def toggle(self, event=None):
            self.mode = "dark" if self.mode == "light" else "light"

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    child = next(iter(_loop(mounted).instances.values()))

    ab = _attr_binding(child, "class")
    assert ab is not None and ab.node.getAttribute("class") == "item light"

    # In-place parent change that does NOT regenerate the collection.
    mounted.toggle()

    # The loop body re-renders live even though the collection did not change.
    assert ab.node.getAttribute("class") == "item dark"


# --------------------------------------------------------------------------
# Scalar (non-dict) items get distinct keys from the item itself.
# --------------------------------------------------------------------------
def test_loop_scalar_item_key():
    class Owner(Component):
        @computed(dependencies=[])
        def years_range(self):
            return list(range(2020, 2025))

        def template(self):
            """
            <select>
                <option for="y" in="{years_range}" key="y" value="{y}">{y}</option>
            </select>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    loop = _loop(mounted)

    # One instance per int, keyed by the int itself.
    assert set(loop.instances.keys()) == {2020, 2021, 2022, 2023, 2024}


# --------------------------------------------------------------------------
# Nested loops render (the outer item drives the inner collection).
# --------------------------------------------------------------------------
def test_loop_nested():
    class Owner(Component):
        groups = [{"g": "A", "items": [{"name": "a1"}, {"name": "a2"}]},
                  {"g": "B", "items": [{"name": "b1"}]}]

        def template(self):
            """
            <div>
                <div for="grp" in="{groups}" key="g">
                    <span>{grp['g']}:</span>
                    <div for="it" in="{grp['items']}" key="name">{it['name']}</div>
                </div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    outer = _loop(mounted)
    assert len(outer.instances) == 2

    text = text_of(mounted.__element__)
    # No eval errors, and every inner item renders.
    assert "[Error:" not in text
    for name in ("a1", "a2", "b1"):
        assert name in text


# --------------------------------------------------------------------------
# Non-plain-name collections (subscripted/dotted) work.
# --------------------------------------------------------------------------
def test_loop_dotted_collection():
    class Owner(Component):
        data = {"list": [{"name": "x"}, {"name": "y"}]}

        def template(self):
            """
            <div>
                <div for="it" in="{data['list']}" key="name">{it['name']}</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    text = text_of(mounted.__element__)

    # Renders both items from the subscripted collection.
    assert "x" in text and "y" in text
    assert "[Error:" not in text
