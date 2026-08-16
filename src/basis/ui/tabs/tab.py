from basis.shared.component import Component, IS_CLIENT

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = ffi = None

from basis.shared.reactive import computed

class Tab(Component):
    __tag__ = "ui-tab"
    label = ""
    value = ""
    name = "tabs-group"
    checked = False
    icon = "" # SVG or icon name
    closable = False

    @computed(dependencies=["closable"])
    def is_closable(self):
        return str(self.closable).lower() == "true" or self.closable is True

    @computed(dependencies=["icon"])
    def has_icon(self):
        return bool(self.icon)

    def on_click(self, event):
        # Programmatically check the radio input if it wasn't triggered by the label
        radio = self.__element__.querySelector('input[type="radio"]')
        if radio and not radio.checked:
            radio.checked = True
            # Manually dispatch change event so parents can react
            radio.dispatchEvent(window.Event.new("change", ffi.to_js({"bubbles": True})))

    def on_close(self, event):
        event.stopPropagation()
        event.preventDefault()
        # Emit custom event
        detail = ffi.to_js({"value": self.value})
        self.__element__.dispatchEvent(window.CustomEvent.new("tab-close", ffi.to_js({"detail": detail, "bubbles": True})))

    def on_dragstart(self, event):
        self.__element__.classList.add("dragging")
        event.dataTransfer.setData("text/plain", self.value)
        event.dataTransfer.effectAllowed = "move"

    def on_dragend(self, event):
        self.__element__.classList.remove("dragging")

    def style(self):
        """
        ui-tab {
            display: inline-block;
            position: relative;
            z-index: 1;
        }

        ui-tab:has(.ui-tab-input:checked) {
            z-index: 10;
        }

        .ui-tab-wrapper {
            display: inline-block;
            position: relative;
        }

        .ui-tab-container {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            height: 32px;
            padding: 0 14px;
            cursor: pointer;
            position: relative;
            background: transparent;
            font-size: 13px;
            font-weight: 400;
            color: var(--text-secondary);
            border: 1px solid transparent;
            border-bottom: none;
            transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease;
            white-space: nowrap;
            border-radius: 6px 6px 0 0;
            user-select: none;
            gap: 6px;
            z-index: 1;
        }

        .ui-tab-input {
            position: absolute;
            opacity: 0;
            width: 0;
            height: 0;
        }

        .ui-tab-container:hover {
            color: var(--text-primary);
            background: var(--hover-bg, rgba(255, 255, 255, 0.04));
        }

        .ui-tab-input:checked + .ui-tab-container {
            background-color: var(--bg-primary, #1e1e1e);
            border: 1px solid var(--border-color, rgba(255, 255, 255, 0.08));
            border-bottom: 1px solid var(--bg-primary, #1e1e1e);
            border-radius: 6px 6px 1px 1px;
            color: var(--text-primary);
            font-weight: 500;
            z-index: 10;
            position: relative;
            box-shadow: 0 2px 0 0 var(--bg-primary, #1e1e1e);
        }

        .tab-icon {
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            opacity: 0.7;
        }

        .ui-tab-input:checked + .ui-tab-container .tab-icon {
            opacity: 0.95;
            color: var(--accent-purple, #7f6df2);
        }

        .tab-close {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 16px;
            height: 16px;
            border-radius: 3px;
            margin-left: 2px;
            margin-right: -4px;
            opacity: 0.3;
            transition: all 0.15s ease;
        }

        .ui-tab-container:hover .tab-close {
            opacity: 0.7;
        }

        .tab-close:hover {
            opacity: 1 !important;
            background: rgba(255, 255, 255, 0.12);
            color: var(--text-primary);
        }

        ui-tab.dragging {
            opacity: 0.5;
        }
        """

    def template(self):
        """
        <div class="ui-tab-wrapper" 
             draggable="true" 
             ondragstart="{on_dragstart}" 
             ondragend="{on_dragend}"
             onclick="{on_click}">
            <input type="radio" 
                   id="radio-{value}"
                   class="ui-tab-input" 
                   name="{name}" 
                   value="{value}" 
                   {checked} />
            <label for="radio-{value}" class="ui-tab-container">
                <span class="tab-icon" if="{has_icon}">{icon}</span>
                <span class="tab-label">{label}</span>
                <span class="tab-close" if="{is_closable}" onclick="{on_close}">
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </span>
            </label>
        </div>
        """


class TabContent(Component):
    __tag__ = "ui-tab-content"
    
    def style(self):
        """
        ui-tab-content {
            display: block;
            width: 100%;
        }
        .ui-tab-content {
            display: block;
            width: 100%;
        }
        """
        
    @property
    def tab_selected(self):
        checked = self.tabs_selector.querySelector('input[type="radio"]:checked')
        tab_selected_value = checked.value
        if self.value == tab_selected_value:
            return True
        else:
            return False

    def template(self):
        """
        <div class="ui-tab-content">
            <slot></slot>
        </div>
        """
