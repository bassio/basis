"""The ``TitleBar`` — the top bar of the shell (the classic IDE title bar).

Sizing (``height``) is a prop, and at the compact breakpoint the bar becomes the
phone's shorter top app bar (``mobile_height``).
"""
from basis.shared.breakpoints import compact_block
from basis.shared.component import Component

_BASE_CSS = """
shell-title-bar {
    display: contents;
}

.shell-title-bar {
    display: flex;
    box-sizing: border-box;
    flex: 0 0 var(--shell-titlebar-height, 48px);
    background: var(--bg-secondary, #26263a);
    overflow: hidden;
    /* Notch guard (M1.1 D6, tokenized in M1.2): keep content clear of
       the top safe area via the theme's --safe-area-top (defaults to
       env(safe-area-inset-top, 0px) — 0 everywhere except notched
       devices at the physical edge, so desktop layouts are untouched).
       The inline env() fallback keeps it working without the theme
       provider. */
    padding-top: var(--safe-area-top, env(safe-area-inset-top, 0px));
}

.shell-title-bar[data-border="bottom"] { border-bottom: 1px solid var(--border-color, #3a3a52); }
.shell-title-bar[data-border="top"] { border-top: 1px solid var(--border-color, #3a3a52); }
.shell-title-bar[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }
"""

_COMPACT_CSS = """
.shell-title-bar {
    flex: 0 0 var(--shell-titlebar-mobile-height, 44px);
}
"""


class TitleBar(Component):
    """A fixed-height top bar. Its ``<slot>`` holds the app's title content.

    Sizing (``height``), internal layout (``direction``/``gap``/``align``/
    ``justify``) and the ``border`` edge are exposed as props for quick editing.
    """

    __tag__ = "shell-title-bar"

    height = "48px"
    mobile_height = "44px"   # the compact top app bar
    direction = "row"
    gap = "0px"
    align = "center"
    justify = "space-between"
    border = "bottom"   # "none" | "bottom" | "top" | "all"

    style = _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <div class="shell-title-bar" style="--shell-titlebar-height: {height}; --shell-titlebar-mobile-height: {mobile_height};" data-border="{border}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" justify="{justify}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """
