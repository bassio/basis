"""The document regions — ``Header`` / ``Main`` / ``Footer``.

Both shell paradigms name their top and bottom strips the same way, because both are
the same thing: a region of the document. A region **sizes to its content** and owns
the ordering and stickiness of its edge; it carries no height of its own, so what
happens to be inside it decides how tall it is — nav content in a site, a
:class:`~basis.plugins.shell.title_bar.TitleBar` in an app.

- ``Header`` (``shell-header``) — the top region (``<header>``); optional ``sticky``.
- ``Main`` (``:scope``) — the primary content region (``<main>``), grows to fill so
  the footer sits at the bottom.
- ``Footer`` (``:scope``) — the bottom region (``<footer>``).

The regions are token-only skeletons: an app fills their ``<slot>``s (a title bar, nav
links, hero sections, footer columns) and owns the look. A region that nests a *bar*
passes ``border="none"``, because the bar draws the strip's own edge.
"""
from basis.shared.breakpoints import compact_block
from basis.shared.component import Component, scoped

# Register tags referenced by these templates before analysis.
from basis.plugins.shell.stack import Stack  # noqa: F401

_BASE_HEADER_CSS = """
:scope {
    display: contents;
}

.shell-header {
    display: flex;
    box-sizing: border-box;
    background: var(--bg-secondary, #26263a);
}

.shell-header[data-border="bottom"] { border-bottom: 1px solid var(--border-color, #3a3a52); }
.shell-header[data-border="top"] { border-top: 1px solid var(--border-color, #3a3a52); }
.shell-header[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }

.shell-header[data-sticky="True"] {
    position: sticky;
    top: 0;
    z-index: 20;
}
"""

#: At compact a region insets its own content by the page gutter, so a phone's nav never
#: touches the glass — the region still paints edge to edge. A region that wraps a chrome
#: bar opts out, because the bar draws its own full-width strip.
_HEADER_COMPACT_CSS = """
.shell-header {
    padding: 0 var(--page-gutter, 1.5rem);
    height: var(--shell-header-mobile-height, auto);
}

.shell-header[data-gutter="none"] {
    padding: 0;
}
"""

_BASE_MAIN_CSS = """
:scope {
    display: contents;
}

.shell-main {
    display: flex;
    flex: 1 1 auto;
    box-sizing: border-box;
    min-width: 0;
    min-height: 0;
    background: var(--bg-primary, #1e1e2e);
}
"""

_MAIN_COMPACT_CSS = """
.shell-main {
    padding: 0 var(--page-gutter, 1.5rem);
}

.shell-main[data-gutter="none"] {
    padding: 0;
}
"""

_BASE_FOOTER_CSS = """
:scope {
    display: contents;
}

.shell-footer {
    display: flex;
    box-sizing: border-box;
    background: var(--bg-secondary, #26263a);
}

.shell-footer[data-border="top"] { border-top: 1px solid var(--border-color, #3a3a52); }
.shell-footer[data-border="bottom"] { border-bottom: 1px solid var(--border-color, #3a3a52); }
.shell-footer[data-border="all"] { border: 1px solid var(--border-color, #3a3a52); }
"""

_FOOTER_COMPACT_CSS = """
.shell-footer {
    padding: 0.75rem var(--page-gutter, 1.5rem);
}

.shell-footer[data-gutter="none"] {
    padding: 0;
}
"""


class Header(Component):
    """The top region (``<header>``) — a bar skeleton, optionally sticky.

    ``row`` is the right default because a site nav is a row. A bar nested inside does
    not care: it states its own height and full width, so it reads the same in a row
    region and a column one (Decision J in ``MOBILE-M2.1-PLAN.md``).

    At compact the region insets its content by the page gutter and can take a fixed
    ``mobile_height`` (``auto`` keeps the content's own height). ``gutter="none"`` suits
    a region wrapping a chrome bar, which draws its own strip edge to edge.
    """

    __tag__ = "shell-header"

    direction = "row"
    gap = "8px"
    align = "center"
    justify = "space-between"
    border = "bottom"   # "none" | "bottom" | "top" | "all"
    sticky = False      # Python bool — position: sticky; top: 0
    gutter = "page"       # "page" | "none" (the compact inset)
    mobile_height = "auto"  # "auto" | a length for the compact strip

    @classmethod
    @scoped
    def style(cls):
        return _BASE_HEADER_CSS + compact_block(_HEADER_COMPACT_CSS)

    def template(self):
        """
        <header class="shell-header" data-border="{border}" data-sticky="{sticky}" data-gutter="{gutter}" style="--shell-header-mobile-height: {mobile_height};">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" justify="{justify}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </header>
        """


class Main(Component):
    """The primary content region (``<main>``) — grows to fill the frame.

    In a site it holds the document; in an app it holds the working arrangement (an
    activity rail, sidebars and one or more panes), which is why its slot may be
    arranged on either axis. At compact it takes the page gutter, so the document never
    touches the glass — an app whose panes run edge to edge asks for ``gutter="none"``.
    """

    __tag__ = "shell-main"

    direction = "column"
    gap = "0px"
    align = "stretch"
    gutter = "page"  # "page" | "none" (the compact inset)

    @classmethod
    @scoped
    def style(cls):
        return _BASE_MAIN_CSS + compact_block(_MAIN_COMPACT_CSS)

    def template(self):
        """
        <main class="shell-main" data-gutter="{gutter}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </main>
        """


class Footer(Component):
    """The bottom region (``<footer>``) — a bar skeleton.

    Like ``Header`` it sizes to its content, so a status bar hidden at the compact
    breakpoint collapses the footer with it rather than leaving an empty strip. At
    compact its own columns restack (the inner stack already carries the arrangement)
    and its content is inset by the page gutter; ``gutter="none"`` suits a footer
    wrapping a chrome bar.
    """

    __tag__ = "shell-footer"

    direction = "row"
    gap = "8px"
    align = "center"
    justify = "space-between"
    border = "top"   # "none" | "top" | "bottom" | "all"
    gutter = "page"  # "page" | "none" (the compact inset)

    @classmethod
    @scoped
    def style(cls):
        return _BASE_FOOTER_CSS + compact_block(_FOOTER_COMPACT_CSS)

    def template(self):
        """
        <footer class="shell-footer" data-border="{border}" data-gutter="{gutter}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" justify="{justify}" size="1 1 auto" layout="column">
                <slot></slot>
            </shell-stack>
        </footer>
        """
