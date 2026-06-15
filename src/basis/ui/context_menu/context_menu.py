from basis.shared.component import Component, IS_CLIENT
from basis.shared.dag import computed

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = ffi = None


class ContextMenu(Component):
    """
    A positionable context menu overlay component.
    
    Attributes:
        open:  "true" | "" (controls display state)
        x:     X coordinate in pixels (default: 0)
        y:     Y coordinate in pixels (default: 0)
        items: List of dicts representing menu options:
               [{"label": "Rename", "action": "rename"}, {"type": "separator"}, ...]
    """
    __tag__ = "ui-context-menu"

    open = ""
    x = 0
    y = 0
    items = []

    def __init__(self):
        super().__init__()
        self.items = []
        self.open = ""
        self.x = 0
        self.y = 0

        if IS_CLIENT and window:
            self._click_proxy = ffi.create_proxy(self.global_click)
            window.addEventListener("click", self._click_proxy)

    @computed(dependencies=["x", "y"])
    def position_style(self):
        return f"left: {self.x}px; top: {self.y}px;"

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

    def global_click(self, event):
        if not self.open:
            return
        
        # Close the context menu if user clicked outside the component
        if IS_CLIENT and self.__element__:
            if not self.__element__.contains(event.target):
                self.open = ""

    def style(self):
        """
        ui-context-menu {
            display: contents;
        }

        .ui-context-menu {
            position: fixed;
            z-index: 3000;
            background: var(--glass-bg, var(--bg-primary, #ffffff));
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

        .ui-context-menu-item:hover {
            background: var(--hover-bg, rgba(0, 0, 0, 0.05));
        }

        .ui-context-menu-danger {
            color: #ef4444;
        }

        .ui-context-menu-danger:hover {
            background: rgba(239, 68, 68, 0.08);
        }
        """

    def template(self):
        """
        <div class="ui-context-menu {open and 'ui-context-menu-open' or ''}" style="{position_style()}">
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
