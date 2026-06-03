from basis.shared.component import Component, IS_CLIENT
from basis.shared.dag import computed

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = ffi = None

class Tabs(Component):
    __tag__ = "ui-tabs"
    target = ""
    selected_value = ""
    show_add_button = False

    def __init__(self):
        super().__init__()
        self._dragged_tab = None

    def on_tab_change(self, event):
        if event.target.type == "radio":
            self.update_target(event.target.value)

    def update_target(self, selected_value):
        self.selected_value = selected_value

    @computed(dependencies=["show_add_button"])
    def can_add(self):
        return str(self.show_add_button).lower() == "true" or self.show_add_button is True

    def on_add_click(self, event):
        self.node.dispatchEvent(window.CustomEvent.new("add-tab", ffi.to_js({"detail": {}})))

    def on_dragover(self, event):
        event.preventDefault()
        event.dataTransfer.dropEffect = "move"
        
        # Find the tab we are dragging over
        target = event.target.closest("ui-tab")
        if target and self._dragged_tab and target != self._dragged_tab:
            # Determine if we should insert before or after
            rect = target.getBoundingClientRect()
            midpoint = rect.left + rect.width / 2
            if event.clientX < midpoint:
                target.parentNode.insertBefore(self._dragged_tab, target)
            else:
                target.parentNode.insertBefore(self._dragged_tab, target.nextSibling)

    def on_dragstart_internal(self, event):
        self._dragged_tab = event.target.closest("ui-tab")

    def style(self):
        """
        :host {
            display: block;
            width: 100%;
        }

        .ui-tabs-container {
            display: flex;
            align-items: flex-end;
            border-bottom: 1px solid var(--border-color, #495057);
            width: 100%;
            overflow-x: auto;
            overflow-y: hidden;
            scrollbar-width: none; /* Hide scrollbar for cleaner look */
        }

        .ui-tabs-container::-webkit-scrollbar {
            display: none;
        }

        .tabs-slot-wrapper {
            display: flex;
            align-items: flex-end;
        }

        .add-tab-button {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 28px;
            height: 28px;
            margin-bottom: 4px;
            margin-left: 8px;
            border-radius: 6px;
            color: var(--text-secondary);
            cursor: pointer;
            transition: all 0.2s;
        }

        .add-tab-button:hover {
            background: rgba(255, 255, 255, 0.05);
            color: var(--text-primary);
        }
        """

    def template(self):
        """
        <div class="ui-tabs-container" 
             onchange="{on_tab_change}" 
             ondragover="{on_dragover}"
             ondragstart="{on_dragstart_internal}">
            <div class="tabs-slot-wrapper">
                <slot></slot>
            </div>
            <div class="add-tab-button" if="{can_add}" onclick="{on_add_click}">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"></line><line x1="5" y1="12" x2="19" y2="12"></line></svg>
            </div>
        </div>
        """
