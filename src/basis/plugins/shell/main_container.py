"""The ``MainContainer`` — the flexible central area of the shell."""
from basis.shared.component import Component


class MainContainer(Component):
    """A flex-grow central area. Its ``<slot>`` holds the app's main content
    (e.g. a ``<tabs-bar>`` above the editor).

    ``direction``/``gap``/``align`` control the internal layout.
    """

    __tag__ = "shell-main-container"

    direction = "column"
    gap = "0px"
    align = "stretch"

    def style(self):
        """
        shell-main-container {
            display: contents;
        }

        .shell-main-container {
            display: flex;
            box-sizing: border-box;
            background: var(--bg-primary, #1e1e2e);
            overflow: hidden;
            min-width: 0;
            min-height: 0;
        }
        """

    def template(self):
        """
        <div class="shell-main-container" style="flex: 1 1 auto;">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """
