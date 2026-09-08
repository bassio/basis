"""The ``AppShell`` — the whole app frame (the classic IDE shell).

A full-height column Stack: ``TitleBar`` / ``Workspace`` / ``StatusBar``. The
workspace knobs are passed through as snake_case props so the frame can be
tailored from one place. Apps put their own chrome contributions directly into
each part's ``<slot>`` (there is no region indirection layer).
"""
from basis.shared.component import Component

# Register the tags referenced by this template before analysis.
from basis.plugins.shell.title_bar import TitleBar      # noqa: F401
from basis.plugins.shell.workspace import Workspace     # noqa: F401
from basis.plugins.shell.status_bar import StatusBar    # noqa: F401


class AppShell(Component):
    """The default app frame: title bar over a resizeable workspace over a
    status bar, stacked with the ``Stack`` primitive.
    """

    __tag__ = "shell-app"

    titlebar_height = "48px"
    statusbar_height = "28px"
    activitybar_width = "56px"
    sidebar_left_width = "240px"
    sidebar_right_width = "240px"
    sidebar_left_resizeable = True
    sidebar_right_resizeable = True

    def style(self):
        """
        shell-app {
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

    def template(self):
        """
        <!-- Viewport height lives in .shell-app (100vh/100dvh pair) — the class
             is the single source, so the dvh fallback order is deterministic. -->
        <div class="shell-app">
            <shell-stack direction="column" size="1 1 auto">
                <shell-title-bar height="{titlebar_height}"></shell-title-bar>
                <shell-workspace
                    activitybar_width="{activitybar_width}"
                    sidebar_left_width="{sidebar_left_width}"
                    sidebar_right_width="{sidebar_right_width}"
                    sidebar_left_resizeable="{sidebar_left_resizeable}"
                    sidebar_right_resizeable="{sidebar_right_resizeable}"></shell-workspace>
                <shell-status-bar height="{statusbar_height}"></shell-status-bar>
            </shell-stack>
        </div>
        """
