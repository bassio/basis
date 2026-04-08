from pyscript import document, window, ffi
import basis.components.component as component

class Tabs(component.Component):
    __tag__ = "ui-tabs"
    target = ""
    selected_value = ""

    def __init__(self):
        super().__init__()
        # Wait for component to mount to DOM
        window.setTimeout(ffi.create_proxy(self.initialize_tabs), 50)
        
    def initialize_tabs(self):
        print("INITIALIZING TABS")
        checked = self.__element__.querySelector('input[type="radio"]:checked')
        if checked:
            print("checked.value", checked.value)
            self.update_target(checked.value)

    def on_tab_change(self, event):
        self.update_target(event.target.value)

    def update_target(self, selected_value):

        self.selected_value = selected_value

        if self.target in ("", "self", None):
            container = self.__element__
        elif self.target.startswith("#"):
            target_id = self.target.replace("#", "")
            container = document.getElementById(target_id)
        else:
            container = document.querySelector(self.target)
            
        if not container:
            container = self.__element__


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
        }
        """

    def template(self):
        """
        <div class="ui-tabs-container tabs-lifted" onload="{on_tab_change}" onchange="{on_tab_change}">
            <slot></slot>
        </div>
        """
