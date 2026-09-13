"""The interactive fixture component the browser harness clicks.

Counter-local reactive state (no store) plus two declared media queries, so the
harness can assert a live DOM update driven by the client DAG and a live update
driven by a browser ``matchMedia`` listener. The context panel rides along so the
same page also exercises the ``$device`` / ``$network`` probes.
"""

from basis.shared.component import Component

from browser_app.components.context_panel import ContextPanel


class Counter(Component):
    """A component-local reactive counter (SSR → hydrate → live)."""

    __tag__ = "browser-counter"

    count = 0

    def increment(self, event=None):
        """Click handler — bound via ``onclick="{increment}"``."""
        self.count += 1

    def template(self):
        """
        <div class="counter">
            <span class="count">Count: {count}</span>
            <span class="narrow-flag" if="{$layout.narrow}">narrow</span>
            <span class="wide-flag" if="{$layout.wide}">wide</span>
            <button class="inc" type="button" onclick="{increment}">Increment</button>
            <browser-context></browser-context>
        </div>
        """
