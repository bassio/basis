"""The ``AppShell`` — the fixed-viewport frame (the classic IDE shell).

A full-height column: a ``Header`` holding the title bar, a ``Main`` band holding the
workbench arrangement, and a ``Footer`` holding the status bar. The regions are the same
ones the site frame composes — what differs between the two frames is the scroll model,
not the vocabulary.
The workspace knobs are passed through as snake_case props so the frame can be tailored
from one place, and apps put their own chrome contributions directly into each part's
``<slot>`` (there is no region indirection layer).
"""
from basis.shared.styling import compact_block
from basis.shared.component import Component, scoped

# Register the tags referenced by this template before analysis.
from basis.plugins.shell.activity_bar import ActivityBar              # noqa: F401
from basis.plugins.shell.pane import Pane                            # noqa: F401
from basis.plugins.shell.regions import Footer, Header, Main         # noqa: F401
from basis.plugins.shell.sidebar import SidebarLeft, SidebarRight   # noqa: F401
from basis.plugins.shell.splitter import Splitter                    # noqa: F401
from basis.plugins.shell.stack import Stack                          # noqa: F401
from basis.plugins.shell.status_bar import StatusBar                 # noqa: F401
from basis.plugins.shell.title_bar import TitleBar                   # noqa: F401

_BASE_CSS = """
:scope {
    display: contents;
}

.shell-app {
    display: flex;
    width: 100%;
    height: 100vh;   /* fallback: fixed-viewport workbench frame */
    height: 100dvh;  /* dynamic: tracks the URL bar / keyboard / rotation */
    overflow: hidden;
    /* The page-locking frame: a full-bleed drag must not rubber-band /
       pull-to-refresh the whole document. Inner panels use
       `overscroll-behavior: contain` (see ui-scroll-area). */
    overscroll-behavior: none;
    box-sizing: border-box;
    background: var(--bg-primary, #1e1e2e);
    color: var(--text-primary, #e0e0e0);
}
"""

#: A docked nav floats over the frame's bottom edge just as it does over a page, so the
#: frame reserves the strip (published at the root by the nav itself).
_COMPACT_CSS = """
.shell-app {
    padding-bottom: var(--shell-bottom-inset, 0px);
}
"""


class AppShell(Component):
    """The default app frame: a title bar in the header, a workbench band in the main
    region, and a status bar in the footer, stacked with the ``Stack`` primitive.

    The band is one activity rail, two optional sidebars and one pane in a row that
    restacks on a phone (``layout="workbench"``). An app that wants a different
    arrangement — panes side by side, a panel under the editor — composes the same parts
    inside ``Main`` itself.
    """

    __tag__ = "shell-app"

    titlebar_height = "48px"
    statusbar_height = "28px"
    activitybar_width = "56px"
    sidebar_left_width = "240px"
    sidebar_right_width = "240px"
    sidebar_left_resizeable = True
    sidebar_right_resizeable = True

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <!-- Viewport height lives in .shell-app (100vh/100dvh pair) — the class
             is the single source, so the dvh fallback order is deterministic. -->
        <div class="shell-app">
            <shell-stack direction="column" size="1 1 auto">
                <shell-header border="none" gutter="none">
                    <shell-title-bar height="{titlebar_height}"></shell-title-bar>
                </shell-header>
                <!-- The band is composed here rather than by a component of its own: the
                     scaffold composes these same parts, and one way to build the band
                     beats two. `layout="workbench"` is what makes it a phone frame. -->
                <shell-main gutter="none">
                    <shell-stack direction="row" size="1 1 auto" layout="workbench">
                        <shell-activity-bar width="{activitybar_width}"></shell-activity-bar>
                        <shell-sidebar-left width="{sidebar_left_width}"></shell-sidebar-left>
                        <shell-splitter if="{sidebar_left_resizeable}" direction="horizontal"></shell-splitter>
                        <shell-pane></shell-pane>
                        <shell-splitter if="{sidebar_right_resizeable}" direction="horizontal"></shell-splitter>
                        <shell-sidebar-right width="{sidebar_right_width}"></shell-sidebar-right>
                    </shell-stack>
                </shell-main>
                <shell-footer border="none" gutter="none">
                    <shell-status-bar height="{statusbar_height}"></shell-status-bar>
                </shell-footer>
            </shell-stack>
        </div>
        """
