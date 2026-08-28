"""The ``Workspace`` — the middle band of the shell (jotter's workspace area).

A row ``Stack``: ``ActivityBar`` / optional left sidebar / splitter / flex main
container / splitter / optional right sidebar. Activity-bar and sidebar widths
plus resizeability are passed through as snake_case props so the frame can be
tailored from one place.

Splitters are inserted between a sidebar and the main container only when the
sidebar is ``resizeable`` (an ``if=`` binding on the Python-bool flag) — the
shadcn copy-paste composition pattern. Resize stays with the splitter (the
in-betweener); the sidebars themselves carry no ``resizeable`` flag.
"""
from basis.shared.component import Component

# Register tags referenced by this template before analysis.
from basis.plugins.shell.activity_bar import ActivityBar            # noqa: F401
from basis.plugins.shell.sidebar import SidebarLeft, SidebarRight  # noqa: F401
from basis.plugins.shell.main_container import MainContainer        # noqa: F401
from basis.plugins.shell.splitter import Splitter                   # noqa: F401


class Workspace(Component):
    """The middle band: activity bar + sidebars flanking a main container."""

    __tag__ = "shell-workspace"

    activitybar_width = "56px"
    sidebar_left_width = "240px"
    sidebar_right_width = "240px"
    sidebar_left_resizeable = True
    sidebar_right_resizeable = True

    def style(self):
        """
        shell-workspace {
            display: contents;
        }

        .shell-workspace {
            box-sizing: border-box;
            min-width: 0;
            min-height: 0;
            overflow: hidden;
        }
        """

    def template(self):
        """
        <div class="shell-workspace" style="flex: 1 1 auto;">
            <shell-stack direction="row" size="1 1 auto">
                <shell-activity-bar width="{activitybar_width}"></shell-activity-bar>
                <shell-sidebar-left width="{sidebar_left_width}"></shell-sidebar-left>
                <shell-splitter if="{sidebar_left_resizeable}" direction="horizontal"></shell-splitter>
                <shell-main-container></shell-main-container>
                <shell-splitter if="{sidebar_right_resizeable}" direction="horizontal"></shell-splitter>
                <shell-sidebar-right width="{sidebar_right_width}"></shell-sidebar-right>
            </shell-stack>
        </div>
        """
