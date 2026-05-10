from basis.shared.component import Component

class SplitHandle(Component):
    __tag__ = "ui-split-handle"
    direction = "horizontal"

    def style(self):
        """
        ui-split-handle {
            display: block;
            flex: 0 0 4px;
            background-color: var(--border-color, #dee2e6);
            background-clip: padding-box;
            cursor: col-resize;
            transition: background-color 0.2s;
            position: relative;
            z-index: 10;
            
            /* Expand hit area with transparent borders */
            border-left: 4px solid transparent;
            border-right: 4px solid transparent;
            margin-left: -4px;
            margin-right: -4px;
        }

        ui-split-handle[direction="vertical"] {
            flex: 0 0 4px;
            cursor: row-resize;
            width: 100%;
            height: 4px;
            border-left: none;
            border-right: none;
            border-top: 4px solid transparent;
            border-bottom: 4px solid transparent;
            margin-left: 0;
            margin-right: 0;
            margin-top: -4px;
            margin-bottom: -4px;
        }

        ui-split-handle:hover, ui-split-handle[data-dragging="true"] {
            background-color: var(--accent-color, #007acc);
            border-color: rgba(0, 122, 204, 0.3); /* Slightly more visible semi-transparent blue */
        }
        """

    def template(self):
        """
        <div></div>
        """
