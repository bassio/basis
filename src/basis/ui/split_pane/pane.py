from basis.shared.component import Component

class SplitPaneItem(Component):
    __tag__ = "ui-pane"
    initial_size = "auto"
    min_size = "0px"
    max_size = "none"

    def style(self):
        """
        ui-pane {
            display: flex;
            flex-direction: column;
            overflow: hidden;
            min-width: var(--pane-min-size, 0px);
            min-height: var(--pane-min-size, 0px);
            max-width: var(--pane-max-size, none);
            max-height: var(--pane-max-size, none);
            flex: var(--pane-flex, 1 1 auto);
            box-sizing: border-box;
        }

        ui-pane:not([initial-size]), ui-pane[initial-size="auto"] {
            flex: 1 1 0%;
        }
        
        .ui-pane-content {
            flex: 1;
            overflow: hidden;
            display: flex;
            flex-direction: column;
            min-height: 0;
            width: 100%;
            height: 100%;
        }
        """

    def template(self):
        """
        <div class="ui-pane-content" 
             style="--pane-min-size: {min_size}; --pane-max-size: {max_size}; flex-basis: {initial_size};">
            <slot></slot>
        </div>
        """
