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
"""

from basis.shared.component import Component
from basis.shared.element import Element
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
