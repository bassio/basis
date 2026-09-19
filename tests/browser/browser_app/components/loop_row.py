"""A row rendered by a component — the child of a loop, in either shape.

Everything a loop child has to keep after hydration is on this one element: a prop from
the loop (``selected``), a derived spelling of it (``selected_attr``, a ``@computed``),
a text binding of its own (``{label}``), a listener of its own (``onclick``), and
component-local state the listener drives (``taps``).

``taps`` is the tell for a doubled adoption: a click that increments it by two means the
child's listener was attached twice, so its subtree was hydrated twice.
"""

from basis.shared.component import Component
from basis.shared.reactive import computed


class LoopRow(Component):
    """One row, owned by the loop that renders it."""

    __tag__ = "browser-loop-row"

    label = ""
    selected = ""
    taps = 0

    @computed(dependencies=["selected"])
    def selected_attr(self):
        return "true" if str(self.selected).lower() == "true" else "false"

    def tap(self, event=None):
        """Click handler — bound via ``onclick="{tap}"``."""
        self.taps += 1

    def template(self):
        """
        <div class="loop-row" data-selected="{selected_attr}">
            <span class="loop-row-label">{label}</span>
            <button class="loop-row-tap" type="button" onclick="{tap}">{taps}</button>
        </div>
        """
