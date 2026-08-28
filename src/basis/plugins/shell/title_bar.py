"""The ``TitleBar`` — the top bar of the shell (jotter's title-bar)."""
from basis.shared.component import Component


class TitleBar(Component):
    """A fixed-height top bar. Its ``<slot>`` holds the app's title content.

    Sizing (``height``), internal layout (``direction``/``gap``/``align``/
    ``justify``) and the ``border`` edge are exposed as props for quick editing.
    """

    __tag__ = "shell-title-bar"

    height = "48px"
    direction = "row"
    gap = "0px"
    align = "center"
    justify = "space-between"
    border = "bottom"   # "none" | "bottom" | "top" | "all"

    def style(self):
        """
        shell-title-bar {
            display: contents;
        }

        .shell-title-bar {
            display: flex;
            box-sizing: border-box;
            background: var(--bg-secondary, #26263a);
            overflow: hidden;
        }

        .shell-title-bar[data-border="bottom"] { border-bottom: 1px solid var(--border-color, #3a3a52); }
        .shell-title-bar[data-border="top"] { border-top: 1px solid var(--border-color, #3a3a52); }
        .shell-title-bar[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }
        """

    def template(self):
        """
        <div class="shell-title-bar" style="flex: 0 0 {height};" data-border="{border}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" justify="{justify}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """
