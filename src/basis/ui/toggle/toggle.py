from basis.shared.component import Component
from basis.shared.bindings import SetterBinding

class Toggle(Component):
    __tag__ = "ui-toggle"
    first = ""
    second = ""
    value = ""
    update = ""
    checked = False

    def __init_bindings__(self):
        super().__init_bindings__()
        field_to_update = self.update
        self.add_binding(SetterBinding(component_instance=self,
                                       node=self.__element__,
                                       field=field_to_update))

    def on_change(self, event):
        print("Toggle:inside on_change")

        #client
        checkbox = self.__element__.querySelector('.toggle-checkbox')
        
        is_checked = checkbox.checked
        
        print("is_checked", is_checked)
        print("event target value", event.target.value)

        if not is_checked:
            value_to_set = self.first
        else:
            value_to_set = self.second

        print("value_to_set", value_to_set)

        if self.update:
            field_to_update = self.update
            print("field_to_update", field_to_update)
            setattr(self, field_to_update, value_to_set)

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
