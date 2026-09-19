"""The ``SiteShell`` — the document-flow frame.

One of the two frames. It composes the three document regions in normal document flow:
the page scrolls as usual and ``Main`` grows so the footer sits at the bottom. The
fixed-viewport counterpart is ``AppShell``, which stacks a workspace between the same
two regions.
"""
from basis.shared.breakpoints import compact_block
from basis.shared.component import Component, scoped

# Register tags referenced by these templates before analysis.
from basis.plugins.shell.regions import Footer, Header, Main  # noqa: F401

_BASE_CSS = """
:scope {
    display: contents;
}

.shell-site {
    display: flex;
    flex-direction: column;
    min-height: 100vh;   /* fallback */
    min-height: 100dvh;  /* dynamic: tracks the URL bar / rotation */
    box-sizing: border-box;
}
"""

#: A docked nav floats over the page, so the frame reserves the strip it covers. The nav
#: publishes that height at the root (and only while one is docked), so the frame needs
#: to know nothing about it.
_COMPACT_CSS = """
.shell-site {
    padding-bottom: var(--shell-bottom-inset, 0px);
}
"""


class SiteShell(Component):
    """A document-flow site frame: header / main / footer in a min-height column.

    Unlike ``AppShell`` (fixed ``100vh`` viewport, inner scroll), the site shell
    is a ``min-height: 100vh`` column in normal document flow — the page scrolls
    as usual and ``Main`` grows so the footer sits at the bottom.
    """

    __tag__ = "shell-site"

    sticky_header = False  # Python bool — pass through to Header

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <div class="shell-site">
            <shell-header sticky="{sticky_header}"></shell-header>
            <shell-main></shell-main>
            <shell-footer></shell-footer>
        </div>
        """
