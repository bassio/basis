"""The installable fixture's root component.

Mirrors what an app would build from ``$pwa``: the counter proves the page hydrated and
stays reactive, and the tags render the *client-observed* half of the store — a worker
that took control, and an update waiting to be applied — so the browser lane can assert
the registration's lifecycle reached Python as reactive state rather than only that the
browser registered something.
"""

from basis.plugins.mobile import apply_update
from basis.shared.component import Component


class PwaCounter(Component):
    """A counter plus the ``$pwa`` states a test can see in the DOM."""

    __tag__ = "pwa-counter"

    count = 0

    def increment(self, event=None):
        """Click handler — bound via ``onclick="{increment}"``."""
        self.count += 1

    def reload_into_the_new_shell(self, event=None):
        """The update affordance's handler: one call, gated by ``$pwa.ready``."""
        apply_update()

    def template(self):
        """
        <div class="pwa">
            <span class="count">Count: {count}</span>
            <span class="controlled" if="{$pwa.controlled}">controlled</span>
            <span class="ready" if="{$pwa.ready}">ready</span>
            <button class="inc" type="button" onclick="{increment}">Increment</button>
            <button class="update" type="button" if="{$pwa.ready}" onclick="{reload_into_the_new_shell}">Update</button>
        </div>
        """

