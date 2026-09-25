"""The fixture's navigation panel — one ``ui-nav`` in a site header.

The site paradigm, and nothing hand-written beyond the frame: the header holds a brand
and a nav, and the arrangement (inline row on a desktop, docked strip on a phone) is
expected to come from the framework's stylesheet alone.
"""
from basis.plugins.shell.regions import Footer, Header, Main  # noqa: F401
from basis.plugins.shell.site import SiteShell  # noqa: F401
from basis.plugins.ui.nav.nav import Nav  # noqa: F401
from basis.shared.component import Component
from basis.shared.reactive import state


class NavPanel(Component):
    """A site frame whose header carries one nav declaration."""

    __tag__ = "browser-nav-panel"

    links: list = state(default_factory=lambda: [
        {"id": "home", "label": "Home", "href": "/"},
        {"id": "nav", "label": "Nav", "href": "/nav", "icon": "🧭"},
        {"id": "elsewhere", "label": "Elsewhere", "href": "/elsewhere", "badge": "3"},
    ])

    def style(self):
        """
        browser-nav-panel {
            display: contents;
        }

        body { margin: 0; }

        .brand {
            font: 600 0.9rem/1 system-ui, sans-serif;
            color: var(--text-primary, #fff);
            padding: 0 0.5rem;
        }

        .nav-body {
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
                <ui-nav items="{links}"></ui-nav>
            </shell-header>
            <shell-main>
                <div class="nav-body">Content that the docked bar must not cover.</div>
            </shell-main>
            <shell-footer>
                <span class="nav-body">Footer</span>
            </shell-footer>
        </shell-site>
        """
