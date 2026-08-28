"""The ``Stack`` layout atom — a positioned flex/grid container.

The smallest layout primitive of the shell: it places its light-DOM children
(typically ``<shell-region-host>``s, chrome parts, or app content) along one axis
with a gap, and can be sized as a flex item of its parent. The host element is
``display: contents`` so the inner box is the real flex item — ``size`` (the
``flex`` shorthand), ``gap``, ``align`` and ``justify`` all behave as expected.

ROADMAP-SHELL.md §5 (Layer A primitive).
"""
from basis.shared.component import Component


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

    def style(self):
        """
        shell-stack {
            display: contents;
        }

        .shell-stack {
            box-sizing: border-box;
            min-width: 0;
            min-height: 0;
        }
        """

    def template(self):
        """
        <div class="shell-stack" style="display: {display}; flex-direction: {direction}; flex: {size}; gap: {gap}; align-items: {align}; justify-content: {justify}; flex-wrap: {wrap}; overflow: {overflow};">
            <slot></slot>
        </div>
        """
