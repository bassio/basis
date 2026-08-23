from basis.shared.component import Component

class ScrollArea(Component):
    __tag__ = "ui-scroll-area"
    orientation = "vertical" # vertical, horizontal, both
    visibility = "auto" # auto, always, hover

    def style(self):
        """
        ui-scroll-area, :host {
            display: flex;
            flex-direction: column;
            width: 100%;
            height: 100%;
            flex: 1;
            min-height: 0;
            overflow: hidden;
            position: relative;
            background: var(--bg-primary, #1e1e1e);
        }

        .ui-scroll-area-viewport {
            width: 100%;
            height: 100%;
            flex: 1;
            min-height: 0;
            padding: 0;
            margin: 0;
            background: var(--bg-primary, #1e1e1e);
            scrollbar-width: thin;
            scrollbar-color: var(--scrollbar-thumb, #888) transparent;
            transition: scrollbar-color 0.3s ease;
        }

        /* Viewport Overflow handling */
        ui-scroll-area[orientation="vertical"] .ui-scroll-area-viewport,
        ui-scroll-area:not([orientation]) .ui-scroll-area-viewport,
        :host([orientation="vertical"]) .ui-scroll-area-viewport,
        :host:not([orientation]) .ui-scroll-area-viewport {
            overflow-y: auto;
            overflow-x: hidden;
        }

        ui-scroll-area[orientation="horizontal"] .ui-scroll-area-viewport,
        :host([orientation="horizontal"]) .ui-scroll-area-viewport {
            overflow-x: auto;
            overflow-y: hidden;
        }

        ui-scroll-area[orientation="both"] .ui-scroll-area-viewport,
        :host([orientation="both"]) .ui-scroll-area-viewport {
            overflow: auto;
        }

        /* Custom Scrollbars (Webkit) */
        .ui-scroll-area-viewport::-webkit-scrollbar {
            width: 8px;
            height: 8px;
        }

        .ui-scroll-area-viewport::-webkit-scrollbar-track {
            background: transparent;
        }

        .ui-scroll-area-viewport::-webkit-scrollbar-thumb {
            background-color: var(--scrollbar-thumb, var(--border-color, #dee2e6));
            border-radius: 10px;
            border: 2px solid transparent;
            background-clip: content-box;
        }

        .ui-scroll-area-viewport::-webkit-scrollbar-thumb:hover {
            background-color: var(--text-secondary, #868b94);
        }

        /* Visibility: hover mode */
        ui-scroll-area[visibility="hover"],
        :host([visibility="hover"]) {
            --scrollbar-thumb: transparent;
        }

        ui-scroll-area[visibility="hover"]:hover,
        :host([visibility="hover"]:hover) {
            --scrollbar-thumb: var(--border-color, #dee2e6);
        }

        /* Visibility: always mode */
        ui-scroll-area[visibility="always"],
        :host([visibility="always"]) {
            --scrollbar-thumb: var(--border-color, #dee2e6);
        }
        """

    def template(self):
        """
        <div class="ui-scroll-area-viewport">
            <slot></slot>
        </div>
        """
