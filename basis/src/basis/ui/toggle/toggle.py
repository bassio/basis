import basis.components.component as component
from pyscript import window

class Toggle(component.Component):
    __tag__ = "ui-toggle"
    first = ""
    second = ""
    value = ""
    bind = ""
    
    def on_change(self, event):
        print("Toggle:inside on_change")
        checkbox = self.__element__.querySelector('.toggle-checkbox')
        is_checked = checkbox.checked
        
        if is_checked:
            self.value = self.first
        else:
            self.value = self.second
        
    def style(self):
        """
        ui-toggle {
            display: inline-flex;
        }
        .switch-container {
            display: inline-flex;
            align-items: center;
            cursor: pointer;
        }
        .toggle-checkbox {
            display: none;
        }
        .switch {
            position: relative;
            display: inline-flex;
            height: 24px;
            width: 44px;
            align-items: center;
            border-radius: 9999px;
            background-color: var(--bg-tertiary, #e4e4e7);
            transition: background-color 0.2s;
            border: 2px solid transparent;
        }
        .switch-container:hover .switch {
            background-color: #d4d4d8;
        }
        .toggle-checkbox:checked + .switch {
            background-color: var(--accent-color, #007acc);
        }
        .toggle-checkbox:checked + .switch:hover {
            background-color: var(--accent-color, #005a9e);
        }
        .thumb {
            pointer-events: none;
            display: inline-block;
            height: 20px;
            width: 20px;
            transform: translateX(0);
            border-radius: 9999px;
            background-color: #ffffff;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            transition: transform 0.2s cubic-bezier(0.4, 0.0, 0.2, 1);
        }
        .toggle-checkbox:checked + .switch .thumb {
            transform: translateX(20px);
        }
        """

    def template(self):
        """
        <label class="switch-container">
            <input type="checkbox" class="toggle-checkbox" onchange="{on_change}" value="{value}" />
            <span class="switch">
                <span class="thumb"></span>
            </span>
        </label>
        """
