"""The ``Header`` / ``Main`` / ``Footer`` + ``SiteShell`` — the document-flow
(site) layout family.

The workbench frame (``AppShell``) models a fixed-viewport app: title bar over a
resizeable workspace over a status bar. Many web apps / sites use the other
dominant paradigm — document flow with a ``<header>``, ``<main>`` and
``<footer>`` and normal body scrolling. This family provides that structure as
thin, slot-based, semantic parts:

- ``Header`` (``shell-header``) — the site nav bar (``<header>``); optional
  ``sticky``.
- ``Main`` (``shell-main``) — the primary content region (``<main>``), grows to
  fill the shell so the footer sits at the bottom.
- ``Footer`` (``shell-footer``) — the site footer (``<footer>``).
- ``SiteShell`` (``shell-site``) — a document-flow composer: header / main /
  footer in a ``min-height: 100vh`` column (no viewport clamp — the page
  scrolls normally).

All are token-only skeletons; apps fill their ``<slot>``s (nav links, hero,
sections, footer columns) and own the look.
"""
from basis.shared.component import Component

# Register tags referenced by these templates before analysis.
from basis.plugins.shell.stack import Stack  # noqa: F401


class Header(Component):
    """A site header (``<header>``) — nav bar skeleton, optionally sticky."""

    __tag__ = "shell-header"

    direction = "row"
    gap = "8px"
    align = "center"
    justify = "space-between"
    border = "bottom"   # "none" | "bottom" | "top" | "all"
    sticky = False      # Python bool — position: sticky; top: 0

    def style(self):
        """
        shell-header {
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

    def template(self):
        """
        <header class="shell-header" data-border="{border}" data-sticky="{sticky}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" justify="{justify}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </header>
        """


class Main(Component):
    """A site main (``<main>``) — primary content region, grows to fill."""

    __tag__ = "shell-main"

    direction = "column"
    gap = "0px"
    align = "stretch"

    def style(self):
        """
        shell-main {
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

    def template(self):
        """
        <main class="shell-main">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </main>
        """


class Footer(Component):
    """A site footer (``<footer>``) — footer skeleton."""

    __tag__ = "shell-footer"

    direction = "row"
    gap = "8px"
    align = "center"
    justify = "space-between"
    border = "top"   # "none" | "top" | "bottom" | "all"

    def style(self):
        """
        shell-footer {
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

    def template(self):
        """
        <footer class="shell-footer" data-border="{border}">
            <shell-stack direction="{direction}" gap="{gap}" align="{align}" justify="{justify}" size="1 1 auto">
                <slot></slot>
            </shell-stack>
        </footer>
        """


class SiteShell(Component):
    """A document-flow site frame: header / main / footer in a min-height column.

    Unlike ``AppShell`` (fixed ``100vh`` viewport, inner scroll), the site shell
    is a ``min-height: 100vh`` column in normal document flow — the page scrolls
    as usual and ``Main`` grows so the footer sits at the bottom.
    """

    __tag__ = "shell-site"

    sticky_header = False  # Python bool — pass through to Header

    def style(self):
        """
        shell-site {
            display: contents;
        }

        .shell-site {
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            box-sizing: border-box;
        }
        """

    def template(self):
        """
        <div class="shell-site">
            <shell-header sticky="{sticky_header}"></shell-header>
            <shell-main></shell-main>
            <shell-footer></shell-footer>
        </div>
        """
