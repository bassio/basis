from pyscript import document
import basis.components.component as component

class Tab(component.Component):
    __tag__ = "ui-tab"
    label = ""
    value = ""
    name = "tabs-group"
    checked = False

    def style(self):
        """
        .ui-tab-input {
            appearance: none;
            -webkit-appearance: none;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            height: 32px;
            padding: 0 16px;
            position: relative;
            background: transparent;
            font-size: 13px;
            font-weight: 500;
            color: var(--text-secondary, #868b94);
            border: 1px solid transparent;
            border-bottom: none;
            margin-bottom: -1px; /* Overlaps the bottom border of the container */
            transition: color 0.2s ease, background-color 0.2s ease;
            white-space: nowrap;
            /* Lifted look border radius */
            border-radius: 6px 6px 0 0;
            z-index: 0;
            outline: none;
        }

        .ui-tab-input::after {
            content: attr(aria-label);
        }

        .ui-tab-input:hover {
            color: var(--text-primary, #ffffff);
            background: rgba(255,255,255,0.03);
        }

        ui-tab .ui-tab-input:checked {
            background-color: var(--bg-primary, #1e1e1e);
            border-color: var(--border-color, #495057);
            border-bottom: 1px solid var(--bg-primary, #1e1e1e); 
            color: var(--text-primary, #ffffff);
            z-index: 10;
            margin-bottom: -2px;
        }

        /* We achieve the 'lifted' look elegantly through the z-index and border-bottom override 
           which merges the active tab seamlessly with the content container below it. */
        """

    def template(self):
        """
        <input type="radio" 
               class="ui-tab-input" 
               name="{name}" 
               value="{value}" 
               aria-label="{label}" 
               {checked} />
        """


class TabContent(component.Component):
    __tag__ = "ui-tab-content"
    
    def style(self):
        """
        .ui-tab-content {
            display: none; // hide by default
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
        <div class="ui-tab-content" content-for="{value}" >
        </div>
        """
