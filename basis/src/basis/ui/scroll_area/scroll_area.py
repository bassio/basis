from basis.shared.component import Component

class ScrollArea(Component):
    __tag__ = "ui-scroll-area"
    orientation = "vertical" # vertical, horizontal, both
    visibility = "auto" # auto, always, hover

    def style(self):
        """
        :host {
            display: block;
            width: 100%;
            height: 100%;
            overflow: hidden;
            position: relative;
        }

        .ui-scroll-area-viewport {
            width: 100%;
            height: 100%;
            padding: 0;
            margin: 0;
            scrollbar-width: thin;
            scrollbar-color: var(--scrollbar-thumb, #888) transparent;
            transition: scrollbar-color 0.3s ease;
        }

        /* Viewport Overflow handling */
        :host([orientation="vertical"]) .ui-scroll-area-viewport {
            overflow-y: auto;
            overflow-x: hidden;
        }

        :host([orientation="horizontal"]) .ui-scroll-area-viewport {
            overflow-x: auto;
            overflow-y: hidden;
        }

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
        :host([visibility="hover"]) {
            --scrollbar-thumb: transparent;
        }

        :host([visibility="hover"]:hover) {
            --scrollbar-thumb: var(--border-color, #dee2e6);
        }

        /* Visibility: always mode */
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
