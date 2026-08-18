"""
Item 3 of the bindings review (BINDINGS-REVIEW.md): only REACTIVE bindings
(having an ``update()``) contribute their ``fields`` to ``__fields__`` / the DAG.

An ``EventBinding`` is a pure DOM listener — its target is a handler METHOD
name, which is never a state field.  Before the fix its ``[target_fn]`` leaked
into ``__fields__``, creating a dead ``StateNode`` named after the handler and
a stale bound-method snapshot in ``_capture_state`` (HMR).
"""

from basis.shared.component import Component
from basis.shared.bindings import EventBinding
from basis.shared.element import Element


def test_event_handler_name_does_not_pollute_fields_or_dag():
    class Owner(Component):
        count = 0

        def on_select(self, event=None):
            pass

        def template(self):
            """
            <div>
                <button onclick="{on_select}">{count}</button>
            </div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))

    # The reactive text binding on {count} registers 'count'.
    assert "count" in mounted.__fields__
    assert "count" in mounted._dag.nodes

    # The event handler name is NOT a state field — it stays out of the state
    # graph entirely (no __fields__ entry, no StateNode).
    assert "on_select" not in mounted.__fields__
    assert "on_select" not in mounted._dag.nodes

    # The EventBinding still exists — it is a listener, just not an effect.
    assert any(isinstance(b, EventBinding) for b in mounted.__bindings__)

    # _capture_state (HMR) never snapshots the handler.
    state = mounted._capture_state()
    assert "count" in state
    assert "on_select" not in state


def test_event_binding_fields_is_empty():
    class Owner(Component):
        def on_select(self, event=None):
            pass

        def template(self):
            """
            <div><button onclick="{on_select}">x</button></div>
            """

    mounted = Owner.mount(Element("div", attrs={}, children=[]))
    eb = next(b for b in mounted.__bindings__ if isinstance(b, EventBinding))
    assert eb.fields == []
