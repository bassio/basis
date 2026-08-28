"""The ``Sidebar`` — a fixed-width left/right panel (the classic IDE sidebar).

A *single* component for both sides: the ``side`` prop picks left vs right (and
the default border edge), so there is no separate ``SidebarLeft``/``SidebarRight``
duplication. It is a slot-based skeleton — the app fills its ``<slot>``.

Collapsible (the classic IDE sidebar behavior): ``collapsed`` (Python bool)
renders ``data-state="collapsed"`` and CSS collapses the width — to a thin icon
rail when ``collapsible="icon"``, or to nothing (offcanvas) otherwise. Collapse
is store-free: any button can flip ``data-state`` at runtime, or
``SidebarTrigger`` (``<shell-sidebar-trigger target="#id">``) does it for you.

ROADMAP-SHELL.md §5 (Layer A default chrome).
"""
from basis.shared.component import Component, py_event, IS_CLIENT
from basis.shared.reactive import computed

if IS_CLIENT:
    from pyscript import document  # type: ignore[reportMissingImports]  # client runtime only
else:
    document = None

# Register tags referenced by this template before analysis.
from basis.plugins.shell.stack import Stack  # noqa: F401


class Sidebar(Component):
    """A fixed-width left/right sidebar skeleton, with optional collapse."""

    __tag__ = "shell-sidebar"

    side = "left"          # "left" | "right"
    width = "240px"        # expanded width
    collapsed = False      # Python bool — collapsed state (data-state)
    collapsible = "none"   # "none" | "icon" (rail) | "offcanvas" (hide)
    icon_width = "56px"    # rail width when collapsible="icon" and collapsed
    direction = "column"
    gap = "0px"
    align = "stretch"
    border = "auto"        # "auto" → outer edge (right for left, left for right)

    @computed
    def state_attr(self):
        return "collapsed" if self.collapsed else "expanded"

    @computed
    def border_side(self):
        if self.border != "auto":
            return self.border
        return "right" if self.side == "left" else "left"

    def style(self):
        """
        shell-sidebar {
            display: contents;
        }

        .shell-sidebar {
            --sidebar-width: var(--sidebar-expanded);
            display: flex;
            box-sizing: border-box;
            background: var(--bg-primary, #1e1e2e);
            overflow: hidden;
            transition: flex-basis 0.25s ease;
        }

        .shell-sidebar[data-state="collapsed"] {
            --sidebar-width: 0px;
        }

        .shell-sidebar[data-state="collapsed"][data-collapsible="icon"] {
            --sidebar-width: var(--sidebar-icon);
        }

        .shell-sidebar[data-border="right"] { border-right: 1px solid var(--border-color, #3a3a52); }
        .shell-sidebar[data-border="left"] { border-left: 1px solid var(--border-color, #3a3a52); }
        .shell-sidebar[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }
        """

    def template(self):
        """
        <div class="shell-sidebar" style="--sidebar-expanded: {width}; --sidebar-icon: {icon_width}; flex: 0 0 var(--sidebar-width);" data-state="{state_attr}" data-collapsible="{collapsible}" data-border="{border_side}" data-side="{side}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """


class SidebarTrigger(Component):
    """A button that toggles a sidebar's collapsed state (store-free).

    Mirrors the conventional sidebar trigger: it flips ``data-state`` on the
    target sidebar via ``document.querySelector`` — no store, no component
    wiring. ``target`` is a CSS selector, e.g. ``target="#sidebarRight"``.
    """

    __tag__ = "shell-sidebar-trigger"

    target = ""  # CSS selector of the sidebar to toggle

    @py_event
    def toggle_sidebar(self, event):
        if not self.target or not IS_CLIENT:
            return

        sidebar = document.querySelector(self.target)
        if sidebar is None:
            return
        state = sidebar.getAttribute("data-state") or "expanded"
        new_state = "expanded" if state == "collapsed" else "collapsed"
        sidebar.setAttribute("data-state", new_state)

    def style(self):
        """
        shell-sidebar-trigger {
            display: contents;
        }

        .shell-sidebar-trigger {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 2rem;
            height: 2rem;
            border-radius: 0.375rem;
            background: transparent;
            color: var(--text-secondary, #9a9ab0);
            border: none;
            cursor: pointer;
            transition: all 0.2s;
        }

        .shell-sidebar-trigger:hover {
            background-color: var(--hover-bg, #2a2a3e);
            color: var(--text-primary, #e0e0e0);
        }
        """

    def template(self):
        """
        <button type="button" class="shell-sidebar-trigger" onclick="{toggle_sidebar}" title="Toggle sidebar">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="18" height="18" x="3" y="3" rx="2" ry="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>
        </button>
        """


class SidebarLeft(Sidebar):
    """The left sidebar — a thin ``Sidebar`` subclass pinned to ``side="left"``.

    A distinct tag for DX (``<shell-sidebar-left>``); behaves exactly like
    ``<shell-sidebar side="left">`` (default border = right edge).
    """

    __tag__ = "shell-sidebar-left"
    side = "left"


class SidebarRight(Sidebar):
    """The right sidebar — a thin ``Sidebar`` subclass pinned to ``side="right"``.

    A distinct tag for DX (``<shell-sidebar-right>``); behaves exactly like
    ``<shell-sidebar side="right">`` (default border = left edge).
    """

    __tag__ = "shell-sidebar-right"
    side = "right"
