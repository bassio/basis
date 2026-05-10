from basis.shared.component import Component

class SplitPaneItem(Component):
    __tag__ = "ui-pane"
    initial_size = "auto"
    min_size = "0px"
    max_size = "none"

    def style(self):
        """
        :host {
            display: flex;
            flex-direction: column;
            overflow: hidden;
            min-width: var(--pane-min-size, 0px);
            min-height: var(--pane-min-size, 0px);
            max-width: var(--pane-max-size, none);
            max-height: var(--pane-max-size, none);
            flex: var(--pane-flex, 1 1 0%);
        }
        
        .ui-pane-content {
            flex: 1;
            overflow: auto;
            display: flex;
            flex-direction: column;
        }
        """

    def template(self):
        """
        <div class="ui-pane-content" 
             style="--pane-min-size: {min_size}; --pane-max-size: {max_size}; flex-basis: {initial_size};">
            <slot></slot>
        </div>
        """
