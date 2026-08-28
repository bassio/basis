"""The ``TabsBar`` — a horizontal tab strip (the classic IDE tab strip).

A chrome strip *skeleton*: a fixed-height bar whose ``<slot>`` hosts the actual
interactive tabs. Tab behavior (selection, close, drag, add) is a generic ui
concern, so apps put ``<ui-tabs>`` / ``<ui-tab>`` (from ``basis.plugins.ui.tabs``)
or their own tabs inside this slot — the shell does not reimplement tabs.
"""
from basis.shared.component import Component


class TabsBar(Component):
    """A fixed-height tab strip. Its ``<slot>`` hosts the tab items.

    Sizing (``height``), internal layout (``direction``/``gap``/``align``) and
    the ``border`` edge are exposed as props for quick editing.
    """

    __tag__ = "shell-tabs-bar"

    height = "32px"
    direction = "row"
    gap = "4px"
    align = "center"
    border = "bottom"   # "none" | "bottom" | "top" | "all"

    def style(self):
        """
        shell-tabs-bar {
            display: contents;
        }

        .shell-tabs-bar {
            display: flex;
            box-sizing: border-box;
            background: var(--bg-secondary, #26263a);
            overflow: hidden;
        }

        .shell-tabs-bar[data-border="bottom"] { border-bottom: 1px solid var(--border-color, #3a3a52); }
        .shell-tabs-bar[data-border="top"] { border-top: 1px solid var(--border-color, #3a3a52); }
        .shell-tabs-bar[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }
        """

    def template(self):
        """
        <div class="shell-tabs-bar" style="flex: 0 0 {height};" data-border="{border}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """
