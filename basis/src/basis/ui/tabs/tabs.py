from pyscript import document, window, ffi
import basis.components.component as component

class Tabs(component.Component):
    __tag__ = "ui-tabs"
    target = ""
    
    def __init__(self):
        super().__init__()
        # Wait for component to mount to DOM
        window.setTimeout(ffi.create_proxy(self.initialize_tabs), 50)
        
    def initialize_tabs(self):
        checked = self.__element__.querySelector('input[type="radio"]:checked')
        if checked:
            self.update_target(checked.value)

    def on_tab_change(self, event):
        self.update_target(event.target.value)

    def update_target(self, selected_value):
        if not self.target:
            return

        if self.target.startswith("#"):
            target_id = self.target.replace("#", "")
            container = document.getElementById(target_id)
        else:
            container = document.querySelector(self.target)
            
        if not container:
            return
            
        child_content_for_selected_tab = self.__element__.querySelector(f'[content-for="{selected_value}"]')

        if child_content_for_selected_tab:
            container.innerHTML = child_content_for_selected_tab.innerHTML

    def style(self):
        """
        .ui-tabs-container {
            display: flex;
            flex-wrap: wrap;
            align-items: flex-end;
            border-bottom: 1px solid var(--border-color, #495057);
            width: 100%;
        }

        .ui-tabs-container .ui-tab-content {
            display: none;
            visibility: hidden;
        }
        """

    def template(self):
        """
        <div class="ui-tabs-container tabs-lifted" onload="{on_tab_change}" onchange="{on_tab_change}">
            <slot></slot>
        </div>
        """
