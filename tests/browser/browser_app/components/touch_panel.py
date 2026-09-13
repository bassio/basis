"""The touch fixture's root: catalogue interactions the hover audit changed.

Each case here is something M1.5 altered, so the browser lane can prove the change
on a real engine instead of reading CSS text:

- a ``Button`` — hover styling that must not latch on a tap, and a target that
  grows for a finger;
- an interactive ``Icon`` — a glyph that needs a hit area on a coarse pointer;
- a closable ``Tab`` — a 16px close glyph inside a 32px row;
- the ``$device`` capability fields, which a phone answers for itself *after*
  hydration (the server ships the desktop-safe neutral).
"""

from basis.plugins.ui.button.button import Button  # noqa: F401
from basis.plugins.ui.icon.icon import Icon  # noqa: F401
from basis.plugins.ui.tabs.tab import Tab  # noqa: F401
from basis.shared.component import Component


class TouchPanel(Component):
    __tag__ = "browser-touch-panel"

    taps = 0

    def on_tap(self, event):
        self.taps += 1

    def style(self):
        """
        .touch-panel {
            display: flex;
            flex-direction: column;
            align-items: flex-start;
            gap: 1rem;
            padding: 1rem;
        }

        .touch-panel-capability {
            margin: 0;
            font: 0.85rem/1.4 monospace;
        }
        """

    def template(self):
        """
        <div class="touch-panel">
            <ui-button label="Press" variant="primary" onclick="{on_tap}"></ui-button>
            <ui-icon content="⚙" interactive="True"></ui-icon>
            <ui-tab label="Alpha" value="alpha" name="touch-tabs" closable="True"></ui-tab>
            <p class="touch-panel-capability" data-hover="{$device.hover}" data-pointer="{$device.pointer}" data-taps="{taps}">{$device.pointer} / {taps}</p>
        </div>
        """
