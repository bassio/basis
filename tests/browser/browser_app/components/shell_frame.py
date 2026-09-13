"""The fixture's workbench frame — the responsive shell under a real browser.

Deliberately the *scaffolded* composition (raw shell parts inside one
``layout="workbench"`` stack, plus the drawer's toggle in the title bar), so this lane
exercises the same markup ``basis init`` produces — the arrangement is expected to come
from the framework's stylesheet alone, with nothing hand-written here.
"""
from basis.plugins.shell.activity_bar import ActivityBar  # noqa: F401
from basis.plugins.shell.main_container import MainContainer  # noqa: F401
from basis.plugins.shell.sidebar import (  # noqa: F401
    SidebarLeft,
    SidebarTrigger,
)
from basis.plugins.shell.splitter import Splitter  # noqa: F401
from basis.plugins.shell.stack import Stack  # noqa: F401
from basis.plugins.shell.status_bar import StatusBar  # noqa: F401
from basis.plugins.shell.title_bar import TitleBar  # noqa: F401
from basis.shared.component import Component


class ShellFrame(Component):
    """A workbench frame: title bar / rail + sidebars + main / status bar."""

    __tag__ = "browser-shell-frame"

    def style(self):
        """
        browser-shell-frame {
            display: contents;
        }

        body { margin: 0; }

        .app-container {
            display: flex;
            flex-direction: column;
            width: 100%;
            height: 100dvh;
            overflow: hidden;
        }
        """

    def template(self):
        """
        <div class="app-container">
            <shell-stack direction="column" size="1 1 auto">
                <shell-title-bar>
                    <shell-sidebar-trigger class="drawer-toggle" target="#sidebarLeft"></shell-sidebar-trigger>
                    <span class="app-title">Fixture</span>
                </shell-title-bar>
                <shell-stack direction="row" size="1 1 auto" layout="workbench">
                    <shell-activity-bar>
                        <span slot="top" class="activity-icon">◆</span>
                    </shell-activity-bar>
                    <shell-sidebar-left id="sidebarLeft" width="240px" collapsible="offcanvas">
                        <div class="panel">Sidebar</div>
                    </shell-sidebar-left>
                    <shell-splitter direction="horizontal"></shell-splitter>
                    <shell-main-container>
                        <span class="main-body">Main</span>
                    </shell-main-container>
                </shell-stack>
                <shell-status-bar class="statusbar"><span class="status-item">Ready</span></shell-status-bar>
            </shell-stack>
        </div>
        """
