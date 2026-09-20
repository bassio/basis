from basis.shared.styling import compact_block
from basis.shared.component import Component, IS_CLIENT, extra_style, scoped
from basis.shared.events import on_document
from basis.shared.reactive import computed

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = ffi = None


def _sheet(selector: str) -> str:
    """The action-sheet arrangement for *selector* — one body, two callers.

    ``sheet`` asks for it at every viewport; ``auto`` asks for it only at the compact
    breakpoint, where the bottom edge of the screen is the part a thumb reaches. The
    pointer stops deciding where the menu is either way: the coordinates are custom
    properties, so restating the four offsets is enough to outrank them.
    """
    return f"""\
{selector} {{
    left: 0;
    right: 0;
    top: auto;
    bottom: 0;
    min-width: 0;
    max-height: 70dvh;
    overflow-y: auto;
    border-radius: var(--radius-lg, 0.5rem) var(--radius-lg, 0.5rem) 0 0;
    /* The home indicator would otherwise sit over the last item. */
    padding-bottom: var(--safe-area-bottom, env(safe-area-inset-bottom, 0px));
}}
"""


_SHEET_CSS = _sheet('.ui-context-menu[data-arrangement="sheet"]')
_COMPACT_SHEET_CSS = _sheet('.ui-context-menu[data-arrangement="auto"]')


class ContextMenu(Component):
    """
    A positionable context menu overlay component.
    
    Attributes:
        open:        "true" | "" (controls display state)
        x:           X coordinate in pixels (default: 0)
        y:           Y coordinate in pixels (default: 0)
        items:       List of dicts representing menu options:
                     [{"label": "Rename", "action": "rename"}, {"type": "separator"}, ...]
        arrangement: "auto" | "menu" | "sheet" (default: "auto" — a pointer-anchored
                     menu that becomes a bottom-anchored action sheet at the compact
                     breakpoint)
    """
    __tag__ = "ui-context-menu"

    open = ""
    x = 0
    y = 0
    items = []
    arrangement = "auto"

    def __init__(self):
        super().__init__()
        self.items = []
        self.open = ""
        self.x = 0
        self.y = 0

    @computed
    def is_open(self):
        """``open`` is an attribute-shaped prop (``"true"`` or ``""``)."""
        return bool(self.open)

    @computed(dependencies=["x", "y"])
    def position_vars(self):
        """Anchor coordinates as custom properties, not as declarations.

        An inline ``left``/``top`` outranks every stylesheet rule, so a menu opened
        near a screen edge could not be pulled back into view.
        """
        return f"--ctx-x: {self.x}px; --ctx-y: {self.y}px;"

    # Where the menu sits. An additive block, so an app can restate an arrangement
    # without copying this stylesheet; ``menu`` needs no rule — the pointer position is
    # the base component.
    @classmethod
    @scoped
    @extra_style
    def arrangements(cls):
        return _SHEET_CSS + compact_block(_COMPACT_SHEET_CSS)

    def show(self, x, y):
        self.x = int(x)
        self.y = int(y)
        self.open = "true"

    def close(self):
        self.open = ""

    def handle_item_click(self, event):
        event.stopPropagation()
        target = event.currentTarget
        action = target.getAttribute("data-action")
        self.open = ""

        if IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "select",
                ffi.to_js({"detail": {"action": action}, "bubbles": True})
            ))

    @on_document("click", when="is_open")
    def close_on_outside_click(self, event):
        """A click outside the menu closes it.

        Page-level, because the outside *is* the page, and gated so a closed menu never pays
        for the check. A click inside the menu is left alone — the menu's own handlers
        decide what happens then.
        """
        element = self.__element__
        if element and not element.contains(event.target):
            self.open = ""

    @scoped
    def style(self):
        """
        :scope {
            display: contents;
        }

        .ui-context-menu {
            position: fixed;
            left: var(--ctx-x, 0);
            top: var(--ctx-y, 0);
            z-index: 3000;
            border: 1px solid var(--border-color, #dee2e6);
            border-radius: var(--radius-md, 0.375rem);
            box-shadow: var(--shadow-md, 0 10px 15px -3px rgba(0, 0, 0, 0.1));
            min-width: 160px;
            padding: 0.25rem 0;
            display: none;
            flex-direction: column;
            pointer-events: auto;
        }

        .ui-context-menu.ui-context-menu-open {
            display: flex;
        }

        .ui-context-menu-separator {
            border: 0;
            height: 1px;
            background: var(--border-color, #dee2e6);
            margin: 0.25rem 0;
        }

        .ui-context-menu-item {
            background: none;
            border: none;
            padding: 0.45rem 1rem;
            text-align: left;
            font-size: 0.85rem;
            color: var(--text-primary, #212529);
            cursor: pointer;
            font-family: inherit;
            font-weight: 500;
            transition: background 0.12s, color 0.12s;
            display: block;
            width: 100%;
        }

        @media (hover: hover) {
            .ui-context-menu-item:hover {
                background: var(--hover-bg, rgba(0, 0, 0, 0.05));
            }

            .ui-context-menu-danger:hover {
                background: rgba(239, 68, 68, 0.08);
            }
        }

        .ui-context-menu-item:active {
            background: var(--hover-bg, rgba(0, 0, 0, 0.05));
        }

        .ui-context-menu-item:focus-visible {
            outline: 2px solid var(--accent-color, #007acc);
            outline-offset: -2px;
        }

        .ui-context-menu-danger {
            color: #ef4444;
        }

        /* Rows are ~28px tall: fine for a cursor, too small for a thumb. */
        @media (pointer: coarse) {
            .ui-context-menu-item {
                min-height: var(--touch-target, 44px);
            }
        }
        """

    def template(self):
        """
        <div class="ui-context-menu {open and 'ui-context-menu-open' or ''}" style="{position_vars()}" data-arrangement="{arrangement}">
            <div for="item" in="{items}" key="label">
                <hr class="ui-context-menu-separator" if="{item.get('type') == 'separator'}" />
                <button 
                    class="ui-context-menu-item {item.get('danger') and 'ui-context-menu-danger' or ''}" 
                    type="button"
                    if="{item.get('type') != 'separator'}"
                    onclick="{handle_item_click}"
                    data-action="{item.get('action', '')}">
                    {item.get('label', '')}
                </button>
            </div>
        </div>
        """
