"""DEPRECATION (planned): ``SplitPaneItem`` (``ui-pane``) is superseded by the
shell model where any ``Stack`` child (shell part or plain element) is a pane,
sized inline via ``flex: 0 0 {size}`` instead of enumerated CSS attribute
selectors. Kept for now because existing apps still use it; it will be removed
once they migrate to the shell primitives.
"""
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
            flex: 1 1 auto;
            box-sizing: border-box;
            height: 100%;
            width: 100%;
        }

        ui-pane[initial-size="220px"] { flex: 0 0 220px; width: 220px; }
        ui-pane[initial-size="240px"] { flex: 0 0 240px; width: 240px; }
        ui-pane[initial-size="20%"] { flex: 0 0 20%; width: 20%; }
        ui-pane[initial-size="60%"] { flex: 0 0 60%; width: 60%; }
        ui-pane[initial-size="100%"] { flex: 1 1 0%; width: 100%; }

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
             style="--pane-min-size: {min_size}; --pane-max-size: {max_size};">
            <slot></slot>
        </div>
        """
