"""
Item 2 (binding lifecycle): ``from_blueprint`` is PURE construction — no DOM
work; ``activate()`` attaches listeners at mount; ``destroy()``/``detach()``
tear them down.  Listener bindings (EventBinding, ModelBinding, FormModelBinding)
own their own attach/detach via the base ``Binding.activate()``/``destroy()``.
"""

from basis.shared.component import Component
from basis.shared.bindings import ChildBinding, EventBinding, FormModelBinding
from basis.shared.element import Element


class Owner(Component):
    def on_click(self, event=None):
        pass

    def template(self):
        """<button onclick="{on_click}">x</button>"""


class _Node:
    """Minimal server-like node with the passive EventTarget surface."""
    def __init__(self, tag_name="form"):
        self.tagName = tag_name
        self._listeners = {}

    def addEventListener(self, event, handler):
        self._listeners.setdefault(event, []).append(handler)

    def removeEventListener(self, event, handler):
        try:
            self._listeners[event].remove(handler)
        except (KeyError, ValueError):
            pass

    def hasAttribute(self, attr):
        return False

    def getAttribute(self, attr):
        return None


def test_event_binding_mount_attaches_via_activate():
    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    eb = next(b for b in mounted.__bindings__ if isinstance(b, EventBinding))
    # activate() ran at mount — the handler is attached exactly once.
    assert len(eb.node._listeners["click"]) == 1


def test_event_binding_direct_construction_is_pure_then_lifecycle():
    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    node = Element("button", attrs={}, children=[])
    eb = EventBinding(
        component_instance=mounted,
        node=node,
        event="onclick",
        target_fn="on_click",
        ast_trees={},
    )
    # Pure construction: no listener until activate().
    assert "_listeners" not in node.__dict__
    eb.activate()
    assert node._listeners["click"]
    eb.destroy()
    assert not node._listeners["click"]


def test_form_model_binding_lifecycle_attach_detach():
    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    node = _Node("form")
    fb = FormModelBinding(
        component_instance=mounted,
        node=node,
        ast_trees={},
        target_expression="x",
        validate_on="input",
    )
    # Pure construction: no __post_init__ listeners, no node-setter attach.
    assert not node._listeners
    fb.activate()
    assert node._listeners["input"] and node._listeners["submit"]
    fb.destroy()
    assert not node._listeners["input"] and not node._listeners["submit"]


def test_if_binding_lifecycle_anchor():
    class IfOwner(Component):
        show = True

        def template(self):
            """
            <div>
                <p if="{show}">hello</p>
            </div>
            """

    mounted = IfOwner.mount(Element("div", attrs={}, children=[]))
    ib = next(b for b in mounted.__bindings__ if b.__class__.__name__ == "IfBinding")
    # from_blueprint is pure; activate() created the anchor.
    assert ib.anchor is not None
    assert ib.anchor.getAttribute("data-if-expression") == "{show}"
    ib.destroy()
    assert ib.anchor is None


def test_child_binding_lifecycle_mount():
    class Child(Component):
        __tag__ = "x-lc-child"

        def template(self):
            """<span>child</span>"""

    class ChildOwner(Component):
        def template(self):
            """
            <div><x-lc-child></x-lc-child></div>
            """

    mounted = ChildOwner.mount(Element("div", attrs={}, children=[]))
    cb = next(b for b in mounted.__bindings__ if isinstance(b, ChildBinding))
    # from_blueprint is pure; activate() mounted the child and linked the node.
    assert cb.childinstance is not None
    assert cb.node.__basis_instance__ is cb.childinstance
    cb.destroy()
    assert cb.childinstance is None


def test_loop_binding_lifecycle():
    class LoopOwner(Component):
        items = []

        def template(self):
            """
            <div>
                <div for="it" in="{items}">{it}</div>
            </div>
            """

    mounted = LoopOwner.mount(Element("div", attrs={}, children=[]))
    lb = next(b for b in mounted.__bindings__ if b.__class__.__name__ == "LoopBinding")
    # activate() removed the loop template node from the DOM.
    assert lb.node.parentNode is None
    # Render an item, then whole-loop destroy() disposes it.
    mounted.items = ["a"]
    lb.update()
    assert len(lb.instances) == 1
    lb.destroy()
    assert len(lb.instances) == 0
