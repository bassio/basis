"""The ``Icon`` — a general-purpose inline icon element.

Renders a glyph (emoji, text, or inline SVG) with an optional tooltip, active
state and click hook. Generalizes the shell's former activity-icon: the shell
activity bar is now a bare skeleton that apps fill with ``<ui-icon>``s.

Conventions: boolean props (``active`` / ``interactive``) are real Python
bools. The click hook (``handle_click``) is a ``@py_event`` behavior seam —
apps subclass ``Icon`` (or put their own ``onclick`` content inside) to act
on a click.
"""
from basis.shared.component import Component
from basis.shared.js import py_event
from basis.shared.reactive import computed


class Icon(Component):
    """A general-purpose inline icon."""

    __tag__ = "ui-icon"

    content = ""         # the glyph (emoji / text / inline SVG)
    title = ""           # tooltip
    size = "1em"         # font-size of the glyph box
    color = ""           # optional color override (token or CSS color)
    view = ""            # optional data-view metadata for click handlers
    active = False       # Python bool — active styling
    interactive = False  # Python bool — pointer cursor + hover

    @computed
    def classes(self):
        """``ui-icon`` plus its modifiers, joined so an absent one leaves no gap.

        A class is how a glyph carries its state: a clickable icon is styleable
        without sniffing a boolean's Python spelling out of a DOM attribute.
        """
        parts = ["ui-icon"]
        if self.active:
            parts.append("active")
        if self.interactive:
            parts.append("interactive")
        return " ".join(parts)

    @computed
    def style_attr(self):
        parts = [f"font-size: {self.size};"]
        if self.color:
            parts.append(f"color: {self.color};")
        return " ".join(parts)

    @py_event
    def handle_click(self, event):
        """Default no-op; override (by subclassing) to act on a click."""
        pass

    def style(self):
        """
        ui-icon {
            display: inline-flex;
        }

        .ui-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            line-height: 1;
            box-sizing: border-box;
            color: var(--text-secondary, #9a9ab0);
            user-select: none;
        }

        .ui-icon.interactive {
            cursor: pointer;
        }

        @media (hover: hover) {
            .ui-icon.interactive:hover {
                color: var(--text-primary, #e0e0e0);
            }
        }

        .ui-icon.interactive:active {
            color: var(--text-primary, #e0e0e0);
        }

        /* A finger needs a real hit area around a glyph. */
        @media (pointer: coarse) {
            .ui-icon.interactive {
                min-width: var(--touch-target, 44px);
                min-height: var(--touch-target, 44px);
            }
        }

        .ui-icon.active {
            color: var(--accent-color, #007acc);
        }
        """

    def template(self):
        """
        <div class="{classes}" title="{title}" data-view="{view}" onclick="{handle_click}" style="{style_attr}">{content}</div>
        """
