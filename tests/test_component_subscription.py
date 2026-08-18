"""
`#id.attr` cross-component reactivity is a first-class DAG edge on the target
component's DAG (mirroring ``Store.add_subscription``).  Subscriptions are not
bindings: they do not contribute to ``__bindings__``/``__fields__`` and need no
tuple-destructuring ``__eq__``/``__iter__`` hacks.
"""

from basis.shared.component import Component
from basis.shared.bindings import TextBinding
from basis.shared.element import Element


def test_component_subscription_updates_subscriber_live():
    class Target(Component):
        __tag__ = "x-sub-target"
        count = 0

        def template(self):
            """<div id="tgt"><span>{count}</span></div>"""

    class Subscriber(Component):
        def template(self):
            """<div><span>{#tgt.count}</span></div>"""

    target = Target.mount(Element("div", attrs={}, children=[]))
    subscriber = Subscriber.mount(Element("div", attrs={}, children=[]))

    tb = next(b for b in subscriber.__bindings__ if isinstance(b, TextBinding))
    assert tb.node.value == "0"

    target.count = 5
    assert tb.node.value == "5"


def test_subscription_is_a_dag_edge_not_a_binding():
    class Target(Component):
        __tag__ = "x-sub-target2"
        count = 0
        hidden = 0  # class attr NOT referenced by the target's own template

        def template(self):
            """<div id="tgt2"><span>{count}</span></div>"""

    class Subscriber(Component):
        def template(self):
            """<div><span>{#tgt2.hidden}</span></div>"""

    target = Target.mount(Element("div", attrs={}, children=[]))
    subscriber = Subscriber.mount(Element("div", attrs={}, children=[]))

    # No ComponentSubscription binding anywhere.
    for comp in (subscriber, target):
        assert not any(
            b.__class__.__name__ == "ComponentSubscription" for b in comp.__bindings__
        )
    # The edge is a DAG effect on the TARGET's DAG.
    assert f"sub_{id(subscriber)}_hidden" in target._dag.nodes
    # The binding's field is tracked on the subscriber...
    assert "#tgt2.hidden" in subscriber.__fields__
    # ...but the subscription no longer pollutes the TARGET's fields (the old
    # add_binding(subscription) added `hidden` to the target's __fields__).
    assert "hidden" not in target.__fields__


def test_pending_subscription_fulfilled_when_target_mounts_later():
    class Target(Component):
        __tag__ = "x-sub-target3"
        count = 10

        def template(self):
            """<div id="tgt3"><span>{count}</span></div>"""

    class Subscriber(Component):
        def template(self):
            """<div><span>{#tgt3.count}</span></div>"""

    # Subscriber mounts first — the target is not in the registry yet.
    subscriber = Subscriber.mount(Element("div", attrs={}, children=[]))
    tb = next(b for b in subscriber.__bindings__ if isinstance(b, TextBinding))
    assert tb.node.value != "10"  # pending — not resolved yet

    target = Target.mount(Element("div", attrs={}, children=[]))
    # Pending subscription is fulfilled and the value flows through.
    assert tb.node.value == "10"
    target.count = 99
    assert tb.node.value == "99"


def test_remove_subscription_removes_dag_edge():
    class Target(Component):
        __tag__ = "x-sub-target4"
        count = 0

        def template(self):
            """<div id="tgt4"><span>{count}</span></div>"""

    class Subscriber(Component):
        def template(self):
            """<div><span>{#tgt4.count}</span></div>"""

    target = Target.mount(Element("div", attrs={}, children=[]))
    subscriber = Subscriber.mount(Element("div", attrs={}, children=[]))
    effect_name = f"sub_{id(subscriber)}_count"
    assert effect_name in target._dag.nodes
    target.remove_subscription(subscriber, "count")
    assert effect_name not in target._dag.nodes
