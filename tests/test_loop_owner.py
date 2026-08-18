"""
Loop-children ownership.

A ``for`` loop over a *plain element* renders each item as a thin ``LoopItem``
(not a Component): the body's bindings are bound to the OWNER and carry a
per-item ``LoopScope``. So:
- event handlers in the loop body run with the owner as ``self``;
- per-item bindings resolve against the item's scope overlay, not the owner.

Custom-element loop children (e.g. ``<x-loop-item for=...>``) remain their own
components with their own handlers (own ``self``).
"""

from basis.shared.component import Component
from basis.shared.bindings import LoopItem
from basis.shared.element import Element


def _loop(owner):
    return next(b for b in owner.__bindings__ if hasattr(b, "instances"))


def _event_binding(item):
    return next(b for b in item.bindings if b.__class__.__name__ == "EventBinding")


def test_plain_loop_item_is_thin_holder_not_component():
    """A plain-element loop child is a thin LoopItem (no DAG) and its handler
    is owner-bound natively."""
    class Owner(Component):
        items = []

        def on_item_click(self, event=None):
            pass

        def template(self):
            """
            <div>
                <div for="it" in="{items}" onclick="{on_item_click}">x</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"id": 1}]

    item = next(iter(_loop(mounted).instances.values()))
    assert isinstance(item, LoopItem)
    assert not hasattr(item, "_dag")


def test_loop_body_handler_runs_on_owner():
    """A handler on the loop element runs with the owner as ``self`` and can
    mutate owner state directly."""
    receivers = []

    class Owner(Component):
        items = []

        def on_item_click(self, event=None):
            receivers.append(self)

        def template(self):
            """
            <div>
                <div for="it" in="{items}" onclick="{on_item_click}">x</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"id": 1}]

    item = next(iter(_loop(mounted).instances.values()))
    handler = _event_binding(item).node._listeners["click"][0]
    handler(None)
    assert receivers == [mounted]


def test_nested_handler_in_loop_body_runs_on_owner():
    """Handlers on NESTED elements inside the loop body are owner-bound too
    (the EventBinding is created with component_instance = owner)."""
    receivers = []

    class Owner(Component):
        items = []

        def on_nested_click(self, event=None):
            receivers.append(self)

        def template(self):
            """
            <div>
                <div for="it" in="{items}">
                    <button onclick="{on_nested_click}">{it['id']}</button>
                </div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"id": 1}]

    item = next(iter(_loop(mounted).instances.values()))
    handler = _event_binding(item).node._listeners["click"][0]
    handler(None)
    assert receivers == [mounted]


def test_custom_element_loop_child_keeps_own_receiver():
    """Custom-element loop children are their own components: their internal
    handlers stay bound to themselves."""
    receivers = []

    class Entry(Component):
        __tag__ = "x-loop-item"
        label = ""

        def on_item_click(self, event=None):
            receivers.append(self)

        def template(self):
            """
            <div class="item" onclick="{on_item_click}">{label}</div>
            """

    class Owner(Component):
        items = []

        def on_item_click(self, event=None):
            receivers.append("owner")

        def template(self):
            """
            <div>
                <x-loop-item for="it" in="{items}" label="{it['label']}"></x-loop-item>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"id": 1, "label": "a"}]

    entry = next(iter(_loop(mounted).instances.values()))
    assert isinstance(entry, LoopItem)      # one entry type for all loops
    child = entry.instance                  # ...holding the mounted component
    assert child is not None

    eb = next(b for b in child.__bindings__ if b.__class__.__name__ == "EventBinding")
    handler = eb.node._listeners["click"][0]
    handler(None)
    assert receivers == [child]


def test_custom_element_loop_child_is_still_a_component_child():
    """A custom-element loop child stays a real component — its mounted
    instance + a ChildBinding in the owner — so SSR hydration still treats it
    as a component root."""
    class Entry(Component):
        __tag__ = "x-loop-item"
        label = ""

        def template(self):
            """
            <div class="item">{label}</div>
            """

    class Owner(Component):
        items = []

        def template(self):
            """
            <div>
                <x-loop-item for="it" in="{items}" key="k" label="{it['label']}"></x-loop-item>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"k": 1, "label": "A"}]

    loop = _loop(mounted)
    entry = next(iter(loop.instances.values()))
    assert entry.instance is not None
    assert isinstance(entry.instance, Entry)

    # The owner keeps a ChildBinding so the child is reachable as a component.
    cb = next(b for b in mounted.__bindings__
              if b.__class__.__name__ == "ChildBinding" and b.loop_binding is loop)
    assert cb.childinstance is entry.instance
    assert entry.instance in [c.childinstance for c in mounted.get_child_bindings(recursive=True)]

    # The custom element's own bindings resolve against itself.
    tb = next(b for b in entry.instance.__bindings__ if b.__class__.__name__ == "TextBinding")
    tb.update()
    assert tb.node.textContent == "A"


def test_plain_loop_exposes_body_bindings_for_hydration():
    """Phase 5-core: a plain loop exposes its owner-bound body bindings via
    all_body_bindings(), so the client hydration pass can re-point them to SSR
    nodes by canonical path -> ssr_map."""
    class Owner(Component):
        items = []

        def template(self):
            """
            <div>
                <div for="it" in="{items}" key="k" class="item-{it['k']}">{it['name']}</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"k": 1, "name": "A"}, {"k": 2, "name": "B"}]

    lb = _loop(mounted)
    body = lb.all_body_bindings()
    # Each item contributes an AttributeBinding (class) + a TextBinding.
    assert len(body) == 4
    for b in body:
        assert b.component_instance is mounted      # owner-bound
        assert b.scope is not None                   # per-item scope overlay
        assert hasattr(b, "node")
    assert lb.component_children() == []            # plain loop: no component roots

    # Simulate a hydration re-point of one body binding to its SSR node.
    ssr_node = Element("div", attrs={"data-hydration-id": "r:0:0"}, children=[])
    tb = next(b for b in body if b.__class__.__name__ == "TextBinding")
    old = tb.node
    tb.node = ssr_node
    assert tb.node is ssr_node and old is not ssr_node


def test_each_loop_item_has_its_own_scope():
    """Each LoopItem carries its own item overlay; no leakage across items."""
    class Owner(Component):
        items = []

        def template(self):
            """
            <div>
                <div for="d" in="{items}" key="id">{d['day_num']}</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"id": 1, "day_num": 17}, {"id": 2, "day_num": 18}, {"id": 3, "day_num": 19}]

    items = list(_loop(mounted).instances.values())
    assert len(items) == 3
    assert [it.scope.vars["d"]["day_num"] for it in items] == [17, 18, 19]
    assert items[0].scope.vars["d"] is not items[1].scope.vars["d"]
    # The owner never sees the loop variable.
    assert not hasattr(mounted, "d")


def test_item_binding_renders_per_item():
    """The body text binding resolves against the item's scope and renders each
    item's own value, with the owner as the live context for non-item names."""
    class Owner(Component):
        items = []
        suffix = "!"

        def template(self):
            """
            <div>
                <div for="d" in="{items}" key="id">{d['day_num']}{suffix}</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"id": 1, "day_num": 17}, {"id": 2, "day_num": 18}]

    items = list(_loop(mounted).instances.values())
    for it, expected in zip(items, ("17!", "18!")):
        tb = next(b for b in it.bindings if b.__class__.__name__ == "TextBinding")
        tb.update()
        assert tb.node.textContent == expected


def test_custom_element_loop_stays_before_trailing_sibling():
    """REGRESSION (2026-08-17, browser): custom-element loop children must stay
    INSIDE the loop block, BEFORE any trailing sibling (e.g. the Jotter
    ComponentShowcase / the status-bar dismiss button). Anchoring on the
    child's inner __element__ (instead of the mounted <custom-element> wrapper)
    used to append every item after the first AFTER the trailing sibling."""
    class Entry(Component):
        __tag__ = "x-loop-item"
        label = ""

        def template(self):
            """
            <div class="item">{label}</div>
            """

    class Owner(Component):
        items = []

        def template(self):
            """
            <div class="container">
                <x-loop-item for="it" in="{items}" key="k" label="{it['label']}"></x-loop-item>
                <div class="showcase">SHOWCASE</div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mounted.items = [{"k": 1, "label": "A"}, {"k": 2, "label": "B"}, {"k": 3, "label": "C"}]

    container = mounted.__element__
    tags = [getattr(c, "tag", None) or "TEXT" for c in container.children]
    # Ignore whitespace text nodes: the sequence must be 3 items, then the showcase.
    non_text = [t for t in tags if t != "TEXT"]
    assert non_text == ["x-loop-item", "x-loop-item", "x-loop-item", "div"], \
        f"loop items not kept before trailing sibling: {tags}"
    # And each item's wrapper is a direct child (not nested inside the child's root).
    first_item_idx = tags.index("x-loop-item")
    wrapper = container.children[first_item_idx]
    assert wrapper.getAttribute("data-item-key") == "1"
