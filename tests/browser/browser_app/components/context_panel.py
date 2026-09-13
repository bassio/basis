"""The fixture's context data plane panel — what the client probes wrote.

Every field ``$device`` / ``$network`` expose is its own text node, so the Playwright
harness can wait on a value without knowing how it was formatted. SSR paints the
neutrals; the probes overwrite them after mount and the DAG re-renders these nodes.
"""

from basis.shared.component import Component


class ContextPanel(Component):
    """Renders the context stores so a browser test can read them."""

    __tag__ = "browser-context"

    def template(self):
        """
        <div class="context">
            <span class="ctx-width">{$device.width}</span>
            <span class="ctx-height">{$device.height}</span>
            <span class="ctx-dpr">{$device.dpr}</span>
            <span class="ctx-orientation">{$device.orientation}</span>
            <span class="ctx-pointer">{$device.pointer}</span>
            <span class="ctx-touch">{$device.touch}</span>
            <span class="ctx-hover">{$device.hover}</span>
            <span class="ctx-reduced-motion">{$device.reduced_motion}</span>
            <span class="ctx-online">{$network.online}</span>
            <span class="ctx-offline">{$network.offline}</span>
            <span class="ctx-effective-type">{$network.effective_type}</span>
        </div>
        """
