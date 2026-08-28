"""The ``StatusBar`` — the bottom bar of the shell (the classic IDE status bar)."""
from basis.shared.component import Component


class StatusBar(Component):
    """A fixed-height bottom bar. Its ``<slot>`` holds the app's status content.

    Sizing (``height``), internal layout (``direction``/``gap``/``align``/
    ``justify``) and the ``border`` edge are exposed as props for quick editing.
    """

    __tag__ = "shell-status-bar"

    height = "28px"
    direction = "row"
    gap = "0px"
    align = "center"
    justify = "flex-start"
    border = "top"   # "none" | "top" | "bottom" | "all"

    def style(self):
        """
        shell-status-bar {
            display: contents;
        }

        .shell-status-bar {
            display: flex;
            box-sizing: border-box;
            background: var(--bg-secondary, #26263a);
            overflow: hidden;
        }

        .shell-status-bar[data-border="top"] { border-top: 1px solid var(--border-color, #3a3a52); }
        .shell-status-bar[data-border="bottom"] { border-bottom: 1px solid var(--border-color, #3a3a52); }
        .shell-status-bar[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }
        """

    def template(self):
        """
        <div class="shell-status-bar" style="flex: 0 0 {height};" data-border="{border}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" justify="{justify}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """
