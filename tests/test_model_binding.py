"""
Item 4 of the bindings review (BINDINGS-REVIEW.md): ``bind="{field}"`` is a
self-attaching ModelBinding.

The old design compiled ``bind`` to TWO blueprints (ModelBinding +
EventBinding) that communicated through a magic ``bind_handler`` attribute on
the component — which worked only by blueprint ordering and broke if a user had
their own ``bind_handler``.  Now ModelBinding owns its two-way input listener
(``attach``): no magic name, no paired EventBinding, and it re-attaches itself
when SSR hydration re-points its node to the live tree.
"""

from basis.shared.component import Component
from basis.shared.bindings import EventBinding, ModelBinding
from basis.shared.element import Element


def _model_binding(mounted):
    return next(b for b in mounted.__bindings__ if isinstance(b, ModelBinding))


def test_bind_input_emits_only_model_binding_and_attaches_listener():
    class Owner(Component):
        name = ""

        def template(self):
            """
            <div><input bind="{name}"></div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))

    mb = _model_binding(mounted)
    assert mb.field == "name"
    assert mb._bound_event == "input"

    # No paired EventBinding and no magic bind_handler attribute.
    assert not any(isinstance(b, EventBinding) for b in mounted.__bindings__)
    assert "bind_handler" not in mounted.__dict__

    # The two-way listener is attached for the input event.
    assert "input" in mb.node._listeners
    assert len(mb.node._listeners["input"]) == 1

    # The bound field is reactive state.
    assert "name" in mounted.__fields__
    assert "name" in mounted._dag.nodes


def test_bind_checkbox_attaches_change_listener():
    class Owner(Component):
        checked = False

        def template(self):
            """
            <div><input type="checkbox" bind="{checked}"></div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mb = _model_binding(mounted)
    assert mb._bound_event == "change"
    assert "change" in mb.node._listeners
    assert "input" not in mb.node._listeners


def test_bind_select_attaches_change_listener():
    class Owner(Component):
        choice = ""

        def template(self):
            """
            <div><select bind="{choice}"></select></div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mb = _model_binding(mounted)
    assert mb._bound_event == "change"
    assert "change" in mb.node._listeners


def test_model_binding_reattaches_on_ssr_node():
    """attach is the hydration re-attach hook: after the binding's node is
    re-pointed to the live SSR node, the listener lands on the new node."""
    class Owner(Component):
        name = ""

        def template(self):
            """
            <div><input bind="{name}"></div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    mb = _model_binding(mounted)

    ssr_node = Element("input", attrs={}, children=[])
    mb.node = ssr_node
    mb.attach(ssr_node)
    assert "input" in ssr_node._listeners
    assert len(ssr_node._listeners["input"]) == 1
