"""The ``MainContainer`` — the flexible central area of the shell.

At the compact breakpoint it stands *above* the rest of the workbench band: it is the
surface the phone arrives on, and the activity bar (the bottom navigation) follows it.
"""
from basis.shared.breakpoints import compact_block
from basis.shared.component import Component

_BASE_CSS = """
shell-main-container {
    display: contents;
}

.shell-main-container {
    display: flex;
    flex: 1 1 auto;
    box-sizing: border-box;
    background: var(--bg-primary, #1e1e2e);
    overflow: hidden;
    min-width: 0;
    min-height: 0;
}
"""

_COMPACT_CSS = """
.shell-stack[data-layout="workbench"] > shell-main-container > .shell-main-container {
    order: 1;
}
"""


class MainContainer(Component):
    """A flex-grow central area. Its ``<slot>`` holds the app's main content
    (e.g. a ``<tabs-bar>`` above the editor).

    ``direction``/``gap``/``align`` control the internal layout.
    """

    __tag__ = "shell-main-container"

    direction = "column"
    gap = "0px"
    align = "stretch"

    style = _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <div class="shell-main-container">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """
