from basis.shared.component import Component, IS_CLIENT

class Tabs(Component):
    __tag__ = "ui-tabs"
    target = ""
    selected_value = ""

    def on_tab_change(self, event):
        self.update_target(event.target.value)

    def update_target(self, selected_value):
        self.selected_value = selected_value


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
