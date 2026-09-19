"""The container-query spike — the fixture for deciding whether components may answer
*their own box* rather than only the viewport.

Three questions, all answered by measurement rather than by reading a spec:

1. does a ``@container`` rule resolve inside this architecture — i.e. with the querying
   element behind a ``display: contents`` host, which is what every Basis component
   renders?
2. can the same component declaration produce two different geometries *on one page*
   (the whole value proposition: a list in a 220px sidebar is not the same as a list in a
   900px pane, at the same viewport)?
3. what does ``container-type: inline-size`` cost the box it is declared on? Inline-size
   containment makes a box ignore its contents when sizing, which is free for a definite
   width and potentially fatal for a shrink-to-fit one.

The probes report geometry (a declared height) and the matched rule (an ``::after``
content string), so a passing test says which query actually fired rather than inferring
it from a colour.
"""
from basis.plugins.shell.pane import Pane  # noqa: F401
from basis.plugins.shell.sidebar import SidebarLeft  # noqa: F401
from basis.plugins.shell.stack import Stack  # noqa: F401
from basis.shared.breakpoints import compact_block, container_block
from basis.shared.component import Component

_BASE_CSS = """
browser-container-panel {
    display: contents;
}

body { margin: 0; }

.spike-root {
    font: 12px/1.4 monospace;
}

/* The candidate containers: a definite width, and a grown flex item. */
.spike-narrow {
    container-type: inline-size;
    container-name: spike;
    flex: 0 0 auto;
    width: 220px;
}

.spike-wide {
    container-type: inline-size;
    container-name: spike;
    flex: 1 1 auto;
}

.spike-frame {
    display: flex;
    height: 60dvh;
}

/* The default probe: the wide layout, which is also what an uncontained box gets. */
.spike-probe {
    height: 33px;
    background: rgb(90, 90, 90);
}

.spike-match::after {
    content: "neither";
}

/* The adoption question: can a *shell part* be the container? A sidebar's width is set,
   a pane's comes from the flex algorithm — neither is content-sized. */
.spike-workbench--contained .shell-sidebar,
.spike-workbench--contained .shell-pane {
    container-type: inline-size;
    container-name: spike;
}

.spike-workbench {
    height: 120px;
}

/* Sizing cost: identical content, one box containing (a container), one not. */
.spike-shrink {
    display: flex;
    gap: 8px;
    /* The controls are deliberately wider than their box; clip them so the page itself
       does not overflow, which would change the layout viewport. */
    overflow: hidden;
}

.spike-plain,
.spike-contained {
    white-space: nowrap;
    background: rgb(120, 120, 120);
}

.spike-contained {
    container-type: inline-size;
}

.spike-both {
    height: 55px;
    background: rgb(60, 60, 60);
}
"""

#: What a narrow box asks for — the same text a component would ship.
_NARROW_CSS = """
.spike-probe {
    height: 22px;
}

.spike-match::after {
    content: "narrow";
}
"""

#: The box scope inside the viewport scope: this is what an app writes when it wants
#: "compact, and only on a phone".
_COMPACT_AND_NARROW_CSS = compact_block(container_block("spike", ".spike-both { height: 44px; }"))


class ContainerPanel(Component):
    """A narrow box and a wide box on one page, plus the sizing-cost controls."""

    __tag__ = "browser-container-panel"

    style = _BASE_CSS + container_block("spike", _NARROW_CSS) + _COMPACT_AND_NARROW_CSS

    def template(self):
        """
        <div class="spike-root">
            <div class="spike-frame">
                <div class="spike-narrow">
                    <div class="spike-probe"></div>
                    <span class="spike-match" data-probe="narrow"></span>
                </div>
                <div class="spike-wide">
                    <div class="spike-probe"></div>
                    <span class="spike-match" data-probe="wide"></span>
                    <div class="spike-both"></div>
                    <div class="spike-shrink">
                        <span class="spike-plain">container query probe</span>
                        <span class="spike-contained">container query probe</span>
                    </div>
                </div>
            </div>
            <div class="spike-workbench">
                <shell-stack direction="row">
                    <shell-sidebar-left width="240px">
                        <div class="spike-probe"></div>
                        <span class="spike-match" data-probe="sidebar"></span>
                    </shell-sidebar-left>
                    <shell-pane>
                        <div class="spike-probe"></div>
                        <span class="spike-match" data-probe="pane"></span>
                    </shell-pane>
                </shell-stack>
            </div>
            <div class="spike-workbench spike-workbench--contained">
                <shell-stack direction="row">
                    <shell-sidebar-left width="240px">
                        <div class="spike-probe"></div>
                        <span class="spike-match" data-probe="sidebar-c"></span>
                    </shell-sidebar-left>
                    <shell-pane>
                        <div class="spike-probe"></div>
                        <span class="spike-match" data-probe="pane-c"></span>
                    </shell-pane>
                </shell-stack>
            </div>
        </div>
        """
