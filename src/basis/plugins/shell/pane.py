"""The ``Pane`` — a content surface inside ``Main``.

A pane grows along whatever axis its stack arranges on, which is what makes panes
axis-agnostic: a row stack gives side-by-side panes, a column stack stacked ones, and
nesting stacks gives both at once (an editor row above a panel row). The pane itself
never decides — it only knows how to fill the space it is given.
"""
from basis.shared.component import Component, scoped

_BASE_CSS = """
:scope {
    display: contents;
}

.shell-pane {
    display: flex;
    flex: 1 1 auto;
    box-sizing: border-box;
    background: var(--bg-primary, #1e1e2e);
    overflow: hidden;
    min-width: 0;
    min-height: 0;
}
"""


class Pane(Component):
    """A flex-grow content surface. Its ``<slot>`` holds the app's content (e.g. a
    ``<shell-tabs-bar>`` above the editor).

    ``direction``/``gap``/``align`` control the layout *inside* the pane. There is no
    compact rule: a pane does not know how many siblings it has, so the parts that can
    rank themselves do (the activity rail puts itself last) and panes keep source order.
    """

    __tag__ = "shell-pane"

    direction = "column"
    gap = "0px"
    align = "stretch"

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS

    def template(self):
        """
        <div class="shell-pane">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """

