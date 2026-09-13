"""The ``Stack`` layout atom — a positioned flex/grid container.

The smallest layout primitive of the shell: it places its light-DOM children
(typically ``<shell-region-host>``s, chrome parts, or app content) along one axis
with a gap, and can be sized as a flex item of its parent. The host element is
``display: contents`` so the inner box is the real flex item — ``size`` (the
``flex`` shorthand), ``gap``, ``align`` and ``justify`` all behave as expected.

Prop values travel as CSS custom properties and *this* class's stylesheet does the
declaring, so the compact breakpoint can restate any of it: the prop stays the single
source of truth and a media query still gets to override the result.
"""
from basis.shared.breakpoints import compact_block
from basis.shared.component import Component

_BASE_CSS = """
shell-stack {
    display: contents;
}

.shell-stack {
    box-sizing: border-box;
    display: var(--stack-display, flex);
    flex-direction: var(--stack-direction, column);
    flex: var(--stack-size, 1);
    gap: var(--stack-gap, 0px);
    align-items: var(--stack-align, stretch);
    justify-content: var(--stack-justify, flex-start);
    flex-wrap: var(--stack-wrap, nowrap);
    overflow: var(--stack-overflow, hidden);
    min-width: 0;
    min-height: 0;
}
"""

# What a stack becomes at the compact breakpoint (see ``basis.shared.breakpoints``).
# ``column`` restacks an authored row on one axis. ``workbench`` restacks it *and*
# names the arrangement the chrome parts key their own compact rules on (the primary
# surface first, the rail last as the phone's bottom navigation) — which is what makes
# an app's frame phone-correct with no app CSS. Only the mode name lives here; which
# part ranks where is the part's business.
_COMPACT_CSS = """
.shell-stack[data-layout="column"],
.shell-stack[data-layout="workbench"] {
    flex-direction: column;
}
"""


class Stack(Component):
    """A positioned flex/grid container — the layout atom of the shell chrome."""

    __tag__ = "shell-stack"

    # Axis + box model.
    display = "flex"        # "flex" | "grid"
    direction = "column"    # "row" | "column" (flex-direction)
    size = "1"              # flex shorthand applied to the inner box
    gap = "0px"
    align = "stretch"       # align-items
    justify = "flex-start"  # justify-content
    wrap = "nowrap"         # flex-wrap
    overflow = "hidden"
    layout = "none"         # "none" | "column" | "workbench" (compact arrangement)

    style = _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <div class="shell-stack" data-layout="{layout}" style="--stack-display: {display}; --stack-direction: {direction}; --stack-size: {size}; --stack-gap: {gap}; --stack-align: {align}; --stack-justify: {justify}; --stack-wrap: {wrap}; --stack-overflow: {overflow};">
            <slot></slot>
        </div>
        """
