"""The fixture's overlay page — four overlays, declared the way an app declares them.

Every one asks for the framework's default arrangement (``auto``), and nothing here
positions anything: the page says *what* the overlays are and the viewport decides
*where* they sit. A pointer-anchored menu stays a menu on a desktop and becomes a
bottom-anchored action sheet on a phone without a line of app CSS — if that took app
CSS, these tests would fail.
"""
from basis.plugins.shell.regions import Footer, Header, Main  # noqa: F401
from basis.plugins.shell.site import SiteShell  # noqa: F401
from basis.plugins.ui.command_palette.command_palette import CommandPalette  # noqa: F401
from basis.plugins.ui.context_menu.context_menu import ContextMenu  # noqa: F401
from basis.plugins.ui.modal.modal import Modal  # noqa: F401
from basis.plugins.ui.toast.toast import ToastContainer  # noqa: F401
from basis.shared.component import Component


class OverlayPanel(Component):
    """A site frame with all four overlays open at once."""

    __tag__ = "browser-overlay-panel"

    items = [
        {"label": "Rename", "action": "rename"},
        {"label": "Duplicate", "action": "duplicate"},
        {"label": "Delete", "action": "delete", "danger": True},
    ]
    commands = [
        {"id": "go", "label": "Go to file", "category": "Nav", "shortcut": "⌘P"},
        {"id": "theme", "label": "Toggle theme", "category": "View"},
    ]

    def style(self):
        """
        browser-overlay-panel {
            display: contents;
        }

        body { margin: 0; }

        .brand {
            font: 600 0.9rem/1 system-ui, sans-serif;
            color: var(--text-primary, #fff);
            padding: 0 0.5rem;
        }

        .overlay-body {
            padding: 1rem;
            color: var(--text-secondary, #aaa);
            font: 0.85rem/1.5 system-ui, sans-serif;
        }
        """

    def template(self):
        """
        <shell-site>
            <shell-header>
                <span class="brand">Fixture</span>
            </shell-header>
            <shell-main>
                <div class="overlay-body">Content the overlays must not disturb.</div>
                <ui-modal open="true" title="Sheet" arrangement="auto">
                    <p>Modal body.</p>
                </ui-modal>
                <ui-context-menu open="true" arrangement="auto" items="{items}"></ui-context-menu>
                <ui-command-palette open="true" arrangement="auto" commands="{commands}"></ui-command-palette>
                <ui-toast-container arrangement="auto"></ui-toast-container>
            </shell-main>
            <shell-footer>
                <span class="overlay-body">Footer</span>
            </shell-footer>
        </shell-site>
        """
