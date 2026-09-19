"""
Loop-body store-field reactivity (LOOP-BINDING-STORE-REACTIVITY.md, Option A).

A ``for`` loop body may reference ``$store.field`` (e.g. a ``class`` binding
like ``{entry['path'] == $docs.path and 'is-active' or ''}``). Those fields
live only in the per-item body blueprints, so the owner's ``__fields__`` never
saw them and the owner was never subscribed to the store — the per-item effect
was wired to a local DAG node that nothing ever triggered (silent staleness).

The fix subscribes the OWNER to each ``$store.*`` field referenced in a loop
body, so a store change → ``owner.react`` → ``trigger_batch`` → the local node
→ the loop-body binding re-renders, exactly like a top-level store binding.

The props of a component mounted by a loop written on its OWN element need the
same wiring and have no body binding to carry it, so they are registered the
same way (they read owner fields, @derived values and ``$store.*`` alike).
"""

from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.reactive import derived
from basis.shared.store import Store


def _loop(owner):
    return next(b for b in owner.__bindings__ if hasattr(b, "instances"))


def test_loop_body_store_field_subscribes_owner_and_rerenders():
    class TestStore(Store):
        pass

    store = TestStore("react_loop_store")
    store.items = [{"path": "a", "title": "A"}, {"path": "b", "title": "B"}]
    store.active = "a"

    class Owner(Component):
        def template(self):
            """
            <div>
                <div for="entry" in="{$react_loop_store.items}"
                     class="{entry['path'] == $react_loop_store.active and 'is-active' or ''}">
                    {entry['title']}
                </div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))

    # The loop body's $store.* reference becomes a subscription field on the
    # owner (collected from the per-item body blueprints), alongside the in= dep.
    assert "$react_loop_store.items" in mounted.__fields__
    assert "$react_loop_store.active" in mounted.__fields__

    # The owner is subscribed to the store's `active` attribute (a sub_ effect
    # registered on the store's DAG).
    sub_effects = [
        n for n in store._dag.nodes if n.startswith("sub_") and n.endswith("_active")
    ]
    assert sub_effects, "no subscription effect for the loop-body store field"

    # Initial render: item 'a' matches active='a'.
    loop = _loop(mounted)
    item0, item1 = loop.instances[0], loop.instances[1]
    assert item0.node.getAttribute("class") == "is-active"
    assert item1.node.getAttribute("class") == ""

    # Changing the store re-renders the loop-body class binding — no manual
    # subscription or component-field mirror needed.
    store.active = "b"
    assert item0.node.getAttribute("class") == ""
    assert item1.node.getAttribute("class") == "is-active"


def test_loop_body_store_field_is_idempotent_across_items():
    """Multiple loop items referencing the same $store.* field must not create
    duplicate subscriptions (add_subscription dedups by (component, attr))."""
    class TestStore(Store):
        pass

    store = TestStore("react_loop_store2")
    store.items = [{"n": 1}, {"n": 2}, {"n": 3}]
    store.active = 1

    class Owner(Component):
        def template(self):
            """
            <div>
                <div for="it" in="{$react_loop_store2.items}"
                     class="{it['n'] == $react_loop_store2.active and 'hot' or ''}">
                    {it['n']}
                </div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))

    sub_effects = [
        n for n in store._dag.nodes if n.startswith("sub_") and n.endswith("_active")
    ]
    assert len(sub_effects) == 1

    # Toggling back and forth re-renders consistently.
    store.active = 2
    loop = _loop(mounted)
    assert loop.instances[0].node.getAttribute("class") == ""
    assert loop.instances[1].node.getAttribute("class") == "hot"
    store.active = 1
    assert loop.instances[0].node.getAttribute("class") == "hot"
    assert loop.instances[1].node.getAttribute("class") == ""


def _rows(mounted):
    """Rendered rows, by the ``data-selected`` flag a row's component prop writes."""
    element = mounted.__element__
    return [
        node.getAttribute("data-selected")
        for node in element.descendants
        if getattr(node, "getAttribute", None)
        and node.getAttribute("class") == "loop-row"
    ]


def test_a_looped_component_prop_subscribes_the_owner_too():
    """A row rendered by a *component* keeps its store-driven prop in step.

    The ``$store.*`` reference sits on the component's PROP binding, not on a body
    element's own binding — so the owner has to be subscribed for those too, or a row
    keeps whatever it was built with (a nav that never moves its highlight)."""
    class TestStore(Store):
        pass

    store = TestStore("react_loop_component_store")
    store.items = [{"path": "a"}, {"path": "b"}]
    store.active = "a"

    class Row(Component):
        __tag__ = "x-loop-store-row"

        selected = ""

        def template(self):
            """<div class="loop-row" data-selected="{selected}">row</div>"""

    class Owner(Component):
        def template(self):
            """
            <div>
                <div for="entry" in="{$react_loop_component_store.items}">
                    <x-loop-store-row
                        selected="{entry['path'] == $react_loop_component_store.active}"></x-loop-store-row>
                </div>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))

    assert "$react_loop_component_store.active" in mounted.__fields__
    sub_effects = [
        n for n in store._dag.nodes if n.startswith("sub_") and n.endswith("_active")
    ]
    assert sub_effects, "no subscription effect for the looped component's prop"

    assert _rows(mounted) == ["True", "False"]

    store.active = "b"
    assert _rows(mounted) == ["False", "True"]


def test_a_looped_component_element_prop_follows_the_store_too():
    """The same prop, with the loop written ON the component element.

    There is no body binding to carry the prop here — it is an attribute of the loop
    element itself, evaluated per item by ``child_props`` — so the owner used to have
    nothing to subscribe and the row kept whatever it was built with. The props are
    wired like a loop body, so the row follows like one."""
    class TestStore(Store):
        pass

    store = TestStore("react_loop_element_store")
    store.items = [{"path": "a"}, {"path": "b"}]
    store.active = "a"

    class Row(Component):
        __tag__ = "x-loop-element-row"

        selected = ""

        def template(self):
            """<div class="loop-row" data-selected="{selected}">row</div>"""

    class Owner(Component):
        def template(self):
            """
            <div>
                <x-loop-element-row for="entry" in="{$react_loop_element_store.items}"
                                    key="path"
                                    selected="{entry['path'] == $react_loop_element_store.active}"></x-loop-element-row>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))

    assert "$react_loop_element_store.active" in mounted.__fields__
    sub_effects = [
        n for n in store._dag.nodes if n.startswith("sub_") and n.endswith("_active")
    ]
    assert len(sub_effects) == 1, "one subscription per (owner, attr), not one per item"

    assert _rows(mounted) == ["True", "False"]

    store.active = "b"
    assert _rows(mounted) == ["False", "True"]


def test_a_looped_component_element_prop_reads_the_owner_and_its_deriveds():
    """A prop on the loop element resolves owner fields and @derived values, exactly
    like a loop body binding — it is evaluated with the item's scope chain."""
    class Row(Component):
        __tag__ = "x-loop-owner-prop-row"

        position = ""

        def template(self):
            """<div class="loop-row" data-selected="{position}">row</div>"""

    class Owner(Component):
        items = [{"n": 1}, {"n": 2}]
        mark = 2

        @derived
        def doubled(self, item):
            return item["n"] * 2

        def template(self):
            """
            <div>
                <x-loop-owner-prop-row for="it" in="{items}" key="n"
                                       position="{doubled}"></x-loop-owner-prop-row>
                <x-loop-owner-prop-row for="it" in="{items}" key="n"
                                       position="{it['n'] == mark}"></x-loop-owner-prop-row>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    assert _rows(mounted)[:2] == ["2", "4"], "the @derived per item"
    assert _rows(mounted)[2:] == ["False", "True"], "an owner field, no [Error: ...]"

    mounted.mark = 1
    assert _rows(mounted)[2:] == ["True", "False"]
