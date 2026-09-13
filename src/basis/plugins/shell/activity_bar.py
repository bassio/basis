"""The ``ActivityBar`` — the vertical icon rail (the classic IDE activity bar).

A bare skeleton: a fixed-width vertical rail with top and bottom icon groups
(named slots ``top`` / ``bottom``), laid out on a column ``Stack`` with
``space-between`` so the two groups sit at opposite ends of the rail. Apps drop
``<ui-icon>``s (from ``basis.plugins.ui.icon``) or their own components into the
slots — the icon itself is not part of the shell.

Behavior-first: sizing (``width``), the internal axis (``direction``/``gap``/
``align``) and the ``border`` edge are exposed as props for quick editing.

At the compact breakpoint the rail becomes the phone's **bottom navigation**: the same
icon groups, one row across the bottom edge with the top group on the left and the
bottom group on the right, padded clear of the home indicator. Labels, badges and
active states belong to the mobile component library — this is the rail, rearranged.
"""
from basis.shared.breakpoints import compact_block
from basis.shared.component import Component

# Register tags referenced by this template before analysis.
from basis.plugins.shell.stack import Stack  # noqa: F401

_BASE_CSS = """
shell-activity-bar {
    display: contents;
}

.shell-activity-bar {
    box-sizing: border-box;
    flex: 0 0 var(--shell-activitybar-width, 56px);
    background: var(--bg-secondary, #26263a);
    overflow: hidden;
}

.shell-activity-bar[data-border="right"] { border-right: 1px solid var(--border-color, #3a3a52); }
.shell-activity-bar[data-border="left"] { border-left: 1px solid var(--border-color, #3a3a52); }
.shell-activity-bar[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }

.shell-activity-top,
.shell-activity-bottom {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    padding: 12px 0;
}
"""

_COMPACT_CSS = """
.shell-activity-bar {
    display: flex;
    flex: 0 0 var(--shell-activitybar-mobile-height, 52px);
    align-items: center;
    justify-content: space-between;
    padding-bottom: var(--safe-area-bottom, env(safe-area-inset-bottom, 0px));
}

/* On the desktop rail the inner stack is the column that holds the two groups.
   Dropping it from the box tree lets the groups become flex items of the bar
   itself, which is a row here. */
.shell-activity-bar > .shell-stack {
    display: contents;
}

.shell-activity-bar .shell-activity-top,
.shell-activity-bar .shell-activity-bottom {
    flex-direction: row;
    gap: 4px;
    padding: 0 10px;
}

/* In a workbench frame the rail is the phone's bottom navigation, so it belongs
   after the primary surface. The box that moves is the inner one: the host is
   ``display: contents``, so its contents are the flex items. */
.shell-stack[data-layout="workbench"] > shell-activity-bar > .shell-activity-bar {
    order: 2;
}
"""


class ActivityBar(Component):
    """A fixed-width vertical icon rail with top / bottom groups."""

    __tag__ = "shell-activity-bar"

    width = "56px"
    mobile_height = "52px"   # the compact bottom navigation bar
    direction = "column"
    gap = "0px"
    align = "center"
    border = "right"   # "none" | "right" | "left" | "all"

    style = _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <div class="shell-activity-bar" style="--shell-activitybar-width: {width}; --shell-activitybar-mobile-height: {mobile_height};" data-border="{border}">
            <shell-stack direction="{direction}" align="{align}" justify="space-between" gap="{gap}" size="1 1 auto">
                <div class="shell-activity-top"><slot name="top"></slot></div>
                <div class="shell-activity-bottom"><slot name="bottom"></slot></div>
            </shell-stack>
        </div>
        """
