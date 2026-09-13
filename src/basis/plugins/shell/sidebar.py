"""The ``Sidebar`` — a fixed-width left/right panel (the classic IDE sidebar).

A *single* component for both sides: the ``side`` prop picks left vs right (and
the default border edge), so there is no separate ``SidebarLeft``/``SidebarRight``
duplication. It is a slot-based skeleton — the app fills its ``<slot>``.

Two independent states, because a docked panel and a drawer are not the same control:

- ``collapsed`` — the **docked** state (``data-state="collapsed"``). The classic IDE
  behavior: CSS collapses the width to a thin icon rail when ``collapsible="icon"``,
  or to nothing (offcanvas) otherwise.
- ``open`` — the **drawer** state (``data-drawer="open"``). Only the compact
  breakpoint reads it, where the sidebar leaves the flow and becomes an overlay that
  slides in from its edge over a backdrop. It defaults to closed, so a phone does not
  open with a panel covering the page.

Both are ordinary props, so a store or a template binding can drive them. The
``SidebarTrigger`` (``<shell-sidebar-trigger target="#id">``) flips whichever one the
current viewport tier uses.
"""
from basis.shared.breakpoints import compact_block
from basis.shared.component import Component, IS_CLIENT
from basis.shared.js import py_event
from basis.shared.reactive import computed

if IS_CLIENT:
    from pyscript import document  # type: ignore[reportMissingImports]  # client runtime only
else:
    document = None

# Register tags referenced by this template before analysis.
from basis.plugins.shell.stack import Stack  # noqa: F401

_BASE_CSS = """
shell-sidebar {
    display: contents;
}

/* The root is the positioning box; the panel surface is the inner stack. That
   split is what lets the compact backdrop paint behind an opaque panel. */
.shell-sidebar {
    --sidebar-width: var(--sidebar-expanded, 240px);
    display: flex;
    box-sizing: border-box;
    flex: 0 0 var(--sidebar-width);
    overflow: hidden;
    transition: flex-basis 0.25s ease;
}

.shell-sidebar > .shell-stack {
    background: var(--bg-primary, #1e1e2e);
}

.shell-sidebar[data-state="collapsed"] {
    --sidebar-width: 0px;
}

.shell-sidebar[data-state="collapsed"][data-collapsible="icon"] {
    --sidebar-width: var(--sidebar-icon, 56px);
}

.shell-sidebar[data-border="right"] > .shell-stack { border-right: 1px solid var(--border-color, #3a3a52); }
.shell-sidebar[data-border="left"] > .shell-stack { border-left: 1px solid var(--border-color, #3a3a52); }
.shell-sidebar[data-border="all"] > .shell-stack { border: 1px solid var(--border-color, #3a3a52); }
"""

_COMPACT_CSS = """
/* The drawer: out of the flow, over the page, sliding in from its own edge. The
   closed position is off-screen rather than transparent, so the panel is either
   there or it is not — and a fixed element off-screen adds no scroll area. */
.shell-sidebar {
    flex: 0 0 auto;
    position: fixed;
    top: 0;
    bottom: 0;
    z-index: 40;
    width: var(--sidebar-mobile-width, min(85vw, 320px));
    transition: left 0.25s ease, right 0.25s ease;
}

.shell-sidebar[data-side="left"] {
    left: calc(-1 * var(--sidebar-mobile-width, min(85vw, 320px)));
    right: auto;
    padding-left: var(--safe-area-left, env(safe-area-inset-left, 0px));
}

.shell-sidebar[data-side="right"] {
    right: calc(-1 * var(--sidebar-mobile-width, min(85vw, 320px)));
    left: auto;
    padding-right: var(--safe-area-right, env(safe-area-inset-right, 0px));
}

.shell-sidebar[data-drawer="open"][data-side="left"] { left: 0; }
.shell-sidebar[data-drawer="open"][data-side="right"] { right: 0; }

.shell-sidebar > .shell-stack {
    box-shadow: var(--shadow-lg, 0 12px 32px rgb(0 0 0 / 0.35));
}

/* The backdrop: a tap target that closes the drawer, painted behind the panel
   (negative z-index inside the drawer's own stacking context). */
.shell-sidebar[data-drawer="open"]::after {
    content: "";
    position: fixed;
    inset: 0;
    z-index: -1;
    background: rgb(0 0 0 / 0.45);
}
"""


class Sidebar(Component):
    """A fixed-width left/right sidebar skeleton, with optional collapse."""

    __tag__ = "shell-sidebar"

    side = "left"          # "left" | "right"
    width = "240px"        # expanded width
    collapsed = False      # Python bool — the docked state (data-state)
    open = False           # Python bool — the drawer state (data-drawer)
    collapsible = "none"   # "none" | "icon" (rail) | "offcanvas" (hide)
    icon_width = "56px"    # rail width when collapsible="icon" and collapsed
    mobile_width = "min(85vw, 320px)"   # drawer width at the compact breakpoint
    direction = "column"
    gap = "0px"
    align = "stretch"
    border = "auto"        # "auto" → outer edge (right for left, left for right)

    @computed
    def state_attr(self):
        return "collapsed" if self.collapsed else "expanded"

    @computed
    def drawer_state(self):
        return "open" if self.open else "closed"

    @computed
    def border_side(self):
        if self.border != "auto":
            return self.border
        return "right" if self.side == "left" else "left"

    @py_event
    def on_backdrop_click(self, event):
        """Close the drawer when the backdrop itself is tapped (the panel does not)."""
        if event.target == self.__element__:
            self.open = False

    style = _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <div class="shell-sidebar" style="--sidebar-expanded: {width}; --sidebar-icon: {icon_width}; --sidebar-mobile-width: {mobile_width};" data-state="{state_attr}" data-drawer="{drawer_state}" data-collapsible="{collapsible}" data-border="{border_side}" data-side="{side}" onclick="{on_backdrop_click}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """


class SidebarTrigger(Component):
    """A button that toggles the sidebar it targets.

    Which state it flips follows the viewport tier, because the sidebar is not the same
    control at both: at the compact breakpoint it is an overlay drawer, so the trigger
    opens and closes it (``open``); on a regular viewport it is docked, so the trigger
    collapses and expands it (``collapsed``). Reading the tier from ``$device`` keeps the
    button and the stylesheet answering the same question.

    The state lives on the target's component instance, so the sidebar's own bindings
    re-render and every trigger pointing at it agrees — the DOM is never the source of
    truth. ``target`` is a CSS selector, e.g. ``target="#sidebarLeft"``.
    """

    __tag__ = "shell-sidebar-trigger"

    target = ""  # CSS selector of the sidebar host to toggle

    def _target_sidebar(self):
        """The target sidebar's component instance, or ``None``."""
        if not self.target or not IS_CLIENT:
            return None
        try:
            element = document.querySelector(self.target)
        except Exception:  # an invalid selector must not take the click down
            return None
        return getattr(element, "__basis_instance__", None) if element else None

    @py_event
    def toggle_sidebar(self, event):
        sidebar = self._target_sidebar()
        if sidebar is None:
            return
        device = self.S.get("device")
        if device is not None and getattr(device, "compact", False):
            sidebar.open = not getattr(sidebar, "open", False)
        else:
            sidebar.collapsed = not getattr(sidebar, "collapsed", False)

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
