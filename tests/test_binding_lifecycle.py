"""
The binding lifecycle: ``from_blueprint`` is PURE construction — no DOM
work; ``activate()`` attaches listeners at mount; ``destroy()`` tears them down.
Listener bindings (EventBinding, ModelBinding, FormModelBinding) attach in
``attach(to_node)`` and hold ``Listener`` objects, so releasing them is the one
shared ``NodeBinding.detach()``.
"""

import pytest

from basis.shared import events
from basis.shared.component import Component
from basis.shared.bindings import ChildBinding, EventBinding, FormModelBinding
from basis.shared.element import Element
from js_fakes import FakeFFI


@pytest.fixture(autouse=True)
def fake_ffi(monkeypatch):
    """A ``Listener`` is inert without a browser, so the registration these tests
    inspect only exists with an ``ffi`` to proxy through."""
    ffi = FakeFFI()
    monkeypatch.setattr(events, "ffi", ffi)
    return ffi


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


def test_event_binding_reattach_releases_from_the_old_node():
    """The SSR re-point pass calls ``attach()`` with a new node; the registration
    left on the old one must not survive it."""
    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    first, second = _Node("button"), _Node("button")
    eb = EventBinding(
        component_instance=mounted,
        node=first,
        event="onclick",
        target_fn="on_click",
        ast_trees={},
    )
    eb.attach(first)
    eb.attach(second)
    assert not first._listeners.get("click")
    assert len(second._listeners["click"]) == 1


def test_event_binding_destroy_frees_the_proxy_with_the_registration(fake_ffi):
    """The two objects share one lifetime: freeing one without the other is the
    failure ``Listener`` exists to prevent."""
    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    node = Element("button", attrs={}, children=[])
    eb = EventBinding(
        component_instance=mounted,
        node=node,
        event="onclick",
        target_fn="on_click",
        ast_trees={},
    )
    eb.activate()
    assert len(eb.listeners) == 1
    proxy = eb.listeners[0].proxy
    eb.destroy()
    assert proxy in fake_ffi.destroyed
    assert not node._listeners.get("click")


def test_a_binding_registers_nothing_without_a_browser(monkeypatch):
    """Inert is the contract: no ``ffi``, no registration, and no proxy to leak."""
    monkeypatch.setattr(events, "ffi", None)
    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    node = Element("button", attrs={}, children=[])
    eb = EventBinding(
        component_instance=mounted,
        node=node,
        event="onclick",
        target_fn="on_click",
        ast_trees={},
    )
    eb.activate()
    assert eb.listeners[0].proxy is None
    assert not getattr(node, "_listeners", {})
    eb.destroy()


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
