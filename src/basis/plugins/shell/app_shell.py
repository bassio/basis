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
            height: 100vh;
            overflow: hidden;
            box-sizing: border-box;
            background: var(--bg-primary, #1e1e2e);
            color: var(--text-primary, #e0e0e0);
        }
        """

    def template(self):
        """
        <div class="shell-app" style="height: 100vh;">
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
