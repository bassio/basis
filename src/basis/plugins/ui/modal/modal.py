from basis.shared.component import Component, IS_CLIENT

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = ffi = None

class Modal(Component):
    """
    A premium, accessible dialog/modal component.
    
    Attributes:
        open              : "true" | "" (reactive attribute to control open state)
        title             : Header title string (optional)
        size              : "sm" | "md" | "lg" | "full" (default: "md")
        close_on_backdrop : "true" | "" (default: "true")
    """
    __tag__ = "ui-modal"

    open = ""
    title = ""
    size = "md"
    close_on_backdrop = "true"

    def close(self, event=None):
        self.open = ""
        if IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "close",
                ffi.to_js({"bubbles": True})
            ))

    def on_backdrop_click(self, event):
        # Only close if target is the backdrop itself
        if event.target == event.currentTarget:
            should_close = str(self.close_on_backdrop).lower() == "true" or self.close_on_backdrop is True
            if should_close:
                self.close()

    def style(self):
        """
        ui-modal {
            display: contents;
        }
        
        .ui-modal-backdrop {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.4);
            display: flex;
            align-items: center;
            justify-content: center;
            z-index: 1000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s ease;
        }

        .ui-modal-backdrop.ui-modal-open {
            opacity: 1;
            pointer-events: auto;
        }

        .ui-modal-panel {
            border: 1px solid var(--border-color, #dee2e6);
            border-radius: var(--radius-lg, 0.5rem);
            box-shadow: var(--shadow-md, 0 10px 15px -3px rgba(0, 0, 0, 0.1));
            display: flex;
            flex-direction: column;
            max-height: 85vh;
            width: 100%;
            overflow: hidden;
            transform: scale(0.95);
            transition: transform 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .ui-modal-backdrop.ui-modal-open .ui-modal-panel {
            transform: scale(1);
        }

        /* Sizing options */
        .ui-modal-sm { max-width: 400px; }
        .ui-modal-md { max-width: 600px; }
        .ui-modal-lg { max-width: 900px; }
        .ui-modal-full { max-width: 95vw; height: 95vh; max-height: 95vh; }

        /* Header, Body, Footer */
        .ui-modal-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 1rem 1.25rem;
            border-bottom: 1px solid var(--border-color, #dee2e6);
        }

        .ui-modal-title {
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--text-primary, #212529);
        }

        .ui-modal-close-btn {
            background: none;
            border: none;
            cursor: pointer;
            color: var(--text-secondary, #6c757d);
            font-size: 1.5rem;
            line-height: 1;
            padding: 0.25rem;
            border-radius: var(--radius-sm, 0.25rem);
            transition: background 0.15s, color 0.15s;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        .ui-modal-close-btn:hover {
            background: var(--hover-bg, rgba(0, 0, 0, 0.05));
            color: var(--text-primary, #212529);
        }

        .ui-modal-body {
            padding: 1.25rem;
            overflow-y: auto;
            color: var(--text-primary, #212529);
            font-size: 0.95rem;
            line-height: 1.5;
        }
        """

    def template(self):
        """
        <div class="ui-modal-backdrop {open and 'ui-modal-open' or ''}" onclick="{on_backdrop_click}">
            <div class="ui-modal-panel ui-modal-{size}">
                <div class="ui-modal-header" if="{title or True}">
                    <span class="ui-modal-title" if="{title}">{title}</span>
                    <span class="ui-modal-title" if="{not title}">&nbsp;</span>
                    <button class="ui-modal-close-btn" type="button" onclick="{close}" aria-label="Close modal">×</button>
                </div>
                <div class="ui-modal-body">
                    <slot></slot>
                </div>
            </div>
        </div>
        """
