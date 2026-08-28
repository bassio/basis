"""The ``ActivityBar`` — the vertical icon rail (the classic IDE activity bar).

A bare skeleton: a fixed-width vertical rail with top and bottom icon groups
(named slots ``top`` / ``bottom``), laid out on a column ``Stack`` with
``space-between`` so the two groups sit at opposite ends of the rail. Apps drop
``<ui-icon>``s (from ``basis.plugins.ui.icon``) or their own components into the
slots — the icon itself is not part of the shell.

Behavior-first: sizing (``width``), the internal axis (``direction``/``gap``/
``align``) and the ``border`` edge are exposed as props for quick editing.
"""
from basis.shared.component import Component

# Register tags referenced by this template before analysis.
from basis.plugins.shell.stack import Stack  # noqa: F401


class ActivityBar(Component):
    """A fixed-width vertical icon rail with top / bottom groups."""

    __tag__ = "shell-activity-bar"

    width = "56px"
    direction = "column"
    gap = "0px"
    align = "center"
    border = "right"   # "none" | "right" | "left" | "all"

    def style(self):
        """
        shell-activity-bar {
            display: contents;
        }

        .shell-activity-bar {
            box-sizing: border-box;
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

    def template(self):
        """
        <div class="shell-activity-bar" style="flex: 0 0 {width};" data-border="{border}">
            <shell-stack direction="{direction}" align="{align}" justify="space-between" gap="{gap}" size="1 1 auto">
                <div class="shell-activity-top"><slot name="top"></slot></div>
                <div class="shell-activity-bottom"><slot name="bottom"></slot></div>
            </shell-stack>
        </div>
        """
