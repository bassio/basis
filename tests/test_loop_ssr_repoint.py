"""
Structural (canonical-path) SSR re-pointing of loops, including nested loops —
`LoopBinding.repoint_to_ssr` (which delegates to
`shared/hydration.repoint_loop_to_ssr`) plus the recursive hydration helpers
(`all_body_bindings` / `text_binding_nodes` / `component_children`).

These run over the server Element model (the same duck-typed tree the client
matcher uses in Pyodide): the client shadow mount and the SSR render are two
separate renders with identical structure, so re-pointing moves item wrappers
and body bindings from the shadow tree onto the SSR tree.
"""

from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.hydration import HydrationReport


def _loop(owner):
    return next(b for b in owner.__bindings__ if b.__class__.__name__ == "LoopBinding")


def _text_of(node):
    if node is None:
        return None
    return getattr(node, "textContent", None) or "".join(
        _text_of(c) for c in getattr(node, "children", [])
    )


class NestedOwner(Component):
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


def test_flat_loop_repoints_to_ssr():
    """A plain (flat) loop's item wrapper + body bindings move onto the SSR
    tree: wrapper matched by data-item-key, body nodes by relative path."""
    class Owner(Component):
        items = [{"k": 1, "name": "Alpha"}, {"k": 2, "name": "Beta"}]

        def template(self):
            """
            <div>
                <div for="it" in="{items}" key="k" class="x">{it['name']}</div>
            </div>
            """

    client = Owner.mount(Element("div", attrs={}, children=[]))
    lb = _loop(client)
    it = next(iter(lb.instances.values()))
    tb = next(b for b in it.bindings if b.__class__.__name__ == "TextBinding")
    old_wrapper = it.node
    old_text_node = tb.node

    # The SSR tree is a separate render (same data -> same structure).
    ssr = Owner.mount(Element("div", attrs={}, children=[]))
    ssr_root = ssr.__element__
    assert it.node is not ssr_root  # distinct trees

    events = lb.repoint_to_ssr(ssr_root, report=None)

    # Wrapper moved onto the SSR tree, keyed as before.
    assert it.node is not old_wrapper
    assert it.node.parentNode is ssr_root
    assert it.node.getAttribute("data-item-key") == "1"
    # Body text node moved onto the SSR tree.
    assert tb.node is not old_text_node
    assert tb.node.parentNode is it.node
    assert events == []  # no body events in this loop
    assert "Alpha" in _text_of(ssr_root)


def test_nested_loop_repoints_recursively_to_ssr():
    """repoint_to_ssr recurses: inner loop item wrappers + inner body bindings
    move onto the SSR tree too (resolved structurally from the outer item)."""
    client = NestedOwner.mount(Element("div", attrs={}, children=[]))
    outer = _loop(client)
    outer_item = next(iter(outer.instances.values()))
    inner_lb = next(b for b in outer_item.bindings
                    if b.__class__.__name__ == "LoopBinding")
    inner_item = next(iter(inner_lb.instances.values()))
    inner_tb = next(b for b in inner_item.bindings
                    if b.__class__.__name__ == "TextBinding")

    old_outer_wrapper = outer_item.node
    old_inner_wrapper = inner_item.node
    old_inner_text = inner_tb.node

    ssr = NestedOwner.mount(Element("div", attrs={}, children=[]))
    ssr_root = ssr.__element__

    outer.repoint_to_ssr(ssr_root, report=None)

    # Outer item wrapper re-pointed to the SSR tree.
    assert outer_item.node is not old_outer_wrapper
    assert outer_item.node.parentNode is ssr_root
    assert outer_item.node.getAttribute("data-item-key") == "A"
    # Inner loop's items re-pointed too (recursion).
    assert inner_item.node is not old_inner_wrapper
    assert inner_item.node.parentNode is outer_item.node
    assert inner_item.node.getAttribute("data-item-key") == "a1"
    # Inner body text re-pointed onto the SSR tree.
    assert inner_tb.node is not old_inner_text
    assert inner_tb.node.parentNode is inner_item.node
    assert inner_tb.node.textContent == "a1"

    text = _text_of(ssr_root)
    assert "A" in text and "B" in text
    assert "a1" in text and "a2" in text and "b1" in text


def test_loop_hydration_helpers_recurse_into_nested_loops():
    """The hydration helpers recurse into nested loops so the server stamps
    inner body nodes + the client can reach inner bindings."""
    mounted = NestedOwner.mount(Element("div", attrs={}, children=[]))
    outer = _loop(mounted)

    body = outer.all_body_bindings()
    assert any(b.__class__.__name__ == "LoopBinding" for b in body), \
        "inner LoopBinding must appear in outer all_body_bindings"

    texts = [n.textContent for n in outer.text_binding_nodes()]
    assert "a1" in texts and "a2" in texts and "b1" in texts, texts

    # Plain nested loop -> no custom-element component roots at any level.
    assert outer.component_children() == []


def test_repoint_to_ssr_custom_element_children_repoint():
    """Custom-element loop children keep their wrapper + instance link on the
    SSR node (their own subtree hydration is a separate pass)."""
    class Entry(Component):
        __tag__ = "x-loop-item"
        label = ""

        def template(self):
            """
            <div>{label}</div>
            """

    class Owner(Component):
        items = []

        def template(self):
            """
            <div>
                <x-loop-item for="it" in="{items}" key="k" label="{it['name']}"></x-loop-item>
            </div>
            """

    client = Owner.mount(Element("div", attrs={}, children=[]))
    client.items = [{"k": 1, "name": "A"}]
    lb = _loop(client)
    it = next(iter(lb.instances.values()))
    assert it.instance is not None  # custom-element child
    old_wrapper = it.node

    ssr = Owner.mount(Element("div", attrs={}, children=[]))
    ssr.items = [{"k": 1, "name": "A"}]
    ssr_root = ssr.__element__

    lb.repoint_to_ssr(ssr_root, report=None)

    assert it.node is not old_wrapper
    assert it.node.parentNode is ssr_root
    assert it.node.getAttribute("data-item-key") == "1"
    # The instance link + ChildBinding follow the live wrapper.
    assert getattr(it.node, "__basis_instance__", None) is it.instance
    assert it.child_binding is not None and it.child_binding.node is it.node


def test_repoint_unmatched_key_reports():
    """An item whose key is absent from the SSR tree is reported, not silently
    dropped."""
    class Owner(Component):
        items = [{"k": 1, "name": "Alpha"}]

        def template(self):
            """
            <div>
                <div for="it" in="{items}" key="k">{it['name']}</div>
            </div>
            """

    client = Owner.mount(Element("div", attrs={}, children=[]))
    lb = _loop(client)
    ssr = Owner.mount(Element("div", attrs={}, children=[]))
    # Break the SSR tree: strip data-item-key so no item matches.
    for child in list(ssr.__element__.children):
        if getattr(child, "attrs", None) is not None:
            child.attrs.pop("data-item-key", None)

    report = HydrationReport()
    lb.repoint_to_ssr(ssr.__element__, report=report)

    assert not report.is_clean
    assert any(u["binding_type"] == "LoopItem" for u in report.unmatched_bindings)


def test_hidden_inner_loop_reports_nothing():
    """An inner loop nested inside an if-hidden branch of a (visible) outer
    loop item is legitimately absent from the SSR tree — re-pointing the outer
    loop must NOT report it as a mismatch.

    Mirrors the jotter WorkspaceCentral quirk (a ``for/in`` loop inside an
    ``if``-gated tab whose branch is hidden at SSR render): the inner loop's
    parent was removed from the client item's own subtree too, so there is no
    relative path to resolve and no SSR counterpart to re-point — the inner
    loop is dormant (kept alive for when its branch reveals), not a genuine
    server/client divergence.
    """
    class Owner(Component):
        show_sub = False
        groups = [{"g": "A"}, {"g": "B"}]
        sub_items = [{"n": "a1"}, {"n": "a2"}]

        def template(self):
            """
            <div>
                <div for="grp" in="{groups}" key="g">
                    <span>{grp['g']}</span>
                    <div if="{show_sub}">
                        <div for="sub" in="{sub_items}" key="n">{sub['n']}</div>
                    </div>
                </div>
            </div>
            """

    client = Owner.mount(Element("div", attrs={}, children=[]))
    outer = _loop(client)
    inner_loops = [
        b for it in outer.instances.values()
        for b in it.bindings if b.__class__.__name__ == "LoopBinding"
    ]
    # Every outer item carries a dormant inner loop: eager instances exist (so
    # reveal can insert them) but its ``if``-parent is detached.
    assert len(inner_loops) == 2
    for il in inner_loops:
        assert il.instances
        assert il.parent is not None and il.parent.parentNode is None

    # A genuine mismatch in the SAME position is still reported (regression
    # guard: we only suppress the hidden case, never real divergences).
    client_b = Owner.mount(Element("div", attrs={}, children=[]))
    outer_b = _loop(client_b)
    outer_item_b = next(iter(outer_b.instances.values()))
    inner_b = next(b for b in outer_item_b.bindings
                   if b.__class__.__name__ == "LoopBinding")
    # Force the inner loop visible: re-attach its if-parent under the item so
    # the client item tree contains it.
    if_parent = inner_b.parent
    outer_item_b.node.children.append(if_parent)

    ssr = Owner.mount(Element("div", attrs={}, children=[]))
    report = HydrationReport()
    outer.repoint_to_ssr(ssr.__element__, report=report)
    assert report.is_clean, report.to_dict()

    # Hidden inner loops stayed untouched (still bound to client nodes) and the
    # visible outer items were re-pointed onto the SSR tree.
    for il in inner_loops:
        assert il.parent.parentNode is None
    for it in outer.instances.values():
        assert it.node.parentNode is ssr.__element__

    # The visible-on-client / absent-on-SSR variant DOES report.
    report2 = HydrationReport()
    outer_b.repoint_to_ssr(ssr.__element__, report=report2)
    assert not report2.is_clean
    assert any(
        u["binding_type"] == "LoopBinding"
        and u["reason"].startswith("inner loop parent not found")
        for u in report2.unmatched_bindings
    )
