"""The ``StatusBar`` — the classic status bar: a thin bar that sits inside a ``Footer``.

At the compact breakpoint the bar is dropped by default: a phone rarely has room for a
status strip beside the bottom navigation, and silently stacking two bottom bars reads
as a bug. An app that wants it back asks for the slim variant with ``mobile="slim"``.
Because a region sizes to its content, hiding the bar collapses the footer with it.
"""
from basis.shared.styling import compact_block
from basis.shared.component import Component, scoped

_BASE_CSS = """
:scope {
    display: contents;
}

.shell-status-bar {
    display: flex;
    box-sizing: border-box;
    /* A bar states its own height and full width rather than a flex basis: it may sit
       in a row region or a column region, and a flex basis is read as a *width* inside
       a row. */
    flex: 0 0 auto;
    width: 100%;
    height: var(--shell-statusbar-height, 28px);
    background: var(--bg-secondary, #26263a);
    overflow: hidden;
    /* Notch guard (M1.1 D6, tokenized in M1.2): keep content clear of
       the bottom safe area (home indicator) via the theme's
       --safe-area-bottom (defaults to env(safe-area-inset-bottom,
       0px) — 0 except notched devices at the physical edge). The
       inline env() fallback keeps it working without the theme
       provider. */
    padding-bottom: var(--safe-area-bottom, env(safe-area-inset-bottom, 0px));
}

.shell-status-bar[data-border="top"] { border-top: 1px solid var(--border-color, #3a3a52); }
.shell-status-bar[data-border="bottom"] { border-bottom: 1px solid var(--border-color, #3a3a52); }
.shell-status-bar[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }
"""

_COMPACT_CSS = """
.shell-status-bar[data-mobile="hidden"] {
    display: none;
}

.shell-status-bar[data-mobile="slim"] {
    height: var(--shell-statusbar-mobile-height, 22px);
}
"""


class StatusBar(Component):
    """A fixed-height bottom bar. Its ``<slot>`` holds the app's status content.

    Sizing (``height``), internal layout (``direction``/``gap``/``align``/
    ``justify``) and the ``border`` edge are exposed as props for quick editing.
    ``mobile`` picks what the bar does at the compact breakpoint.
    """

    __tag__ = "shell-status-bar"

    height = "28px"
    mobile_height = "22px"   # the compact slim bar
    mobile = "hidden"        # "hidden" | "slim"
    direction = "row"
    gap = "0px"
    align = "center"
    justify = "flex-start"
    border = "top"   # "none" | "top" | "bottom" | "all"

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <div class="shell-status-bar" style="--shell-statusbar-height: {height}; --shell-statusbar-mobile-height: {mobile_height};" data-border="{border}" data-mobile="{mobile}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" justify="{justify}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </div>
        """
