"""DEPRECATION (planned): ``SplitPane`` is superseded by the shell's
``Stack`` + ``Splitter`` primitives (``basis.plugins.shell``) — the shell
``Splitter`` is the generalized, self-contained drag-resize divider. Kept for
now because jotter still composes with it; it will be removed after jotter
migrates to the shell primitives.
"""
from basis.shared.component import Component, IS_CLIENT

if IS_CLIENT:
    from pyscript import window, document, ffi
else:
    window = document = ffi = None

class SplitPane(Component):
    __tag__ = "ui-split-pane"
    direction = "horizontal" # horizontal or vertical

    def __init__(self):
        super().__init__()
        self._dragging = False
        self._active_handle = None
        self._prev_pane = None
        self._next_pane = None
        self._start_pos = 0
        self._start_prev_size = 0
        self._start_next_size = 0
        
        self._mousemove_proxy = None
        self._mouseup_proxy = None

    def on_mousedown(self, event):
        handle = event.target.closest("ui-split-handle")
        if not handle:
            return

        event.preventDefault()
        self._dragging = True
        self._active_handle = handle
        handle.setAttribute("data-dragging", "true")

        # Find adjacent panes
        self._prev_pane = handle.previousElementSibling
        self._next_pane = handle.nextElementSibling

        if self.direction == "horizontal":
            self._start_pos = event.clientX
            self._start_prev_size = self._prev_pane.offsetWidth
            self._start_next_size = self._next_pane.offsetWidth
        else:
            self._start_pos = event.clientY
            self._start_prev_size = self._prev_pane.offsetHeight
            self._start_next_size = self._next_pane.offsetHeight

        if not self._mousemove_proxy:
            self._mousemove_proxy = ffi.create_proxy(self.on_mousemove)
            self._mouseup_proxy = ffi.create_proxy(self.on_mouseup)

        window.addEventListener("mousemove", self._mousemove_proxy)
        window.addEventListener("mouseup", self._mouseup_proxy)

    def on_mousemove(self, event):
        if not self._dragging:
            return

        if self.direction == "horizontal":
            delta = event.clientX - self._start_pos
        else:
            delta = event.clientY - self._start_pos

        new_prev_size = self._start_prev_size + delta
        new_next_size = self._start_next_size - delta

        # Minimum size checks (simple fallback)
        if new_prev_size < 20 or new_next_size < 20:
            return

        # Update styles
        if self.direction == "horizontal":
            self._prev_pane.style.width = f"{new_prev_size}px"
            self._prev_pane.style.flex = "0 0 auto"
            self._next_pane.style.width = f"{new_next_size}px"
            self._next_pane.style.flex = "0 0 auto"
        else:
            self._prev_pane.style.height = f"{new_prev_size}px"
            self._prev_pane.style.flex = "0 0 auto"
            self._next_pane.style.height = f"{new_next_size}px"
            self._next_pane.style.flex = "0 0 auto"

    def on_mouseup(self, event):
        if not self._dragging:
            return

        self._dragging = False
        if self._active_handle:
            self._active_handle.removeAttribute("data-dragging")
        
        window.removeEventListener("mousemove", self._mousemove_proxy)
        window.removeEventListener("mouseup", self._mouseup_proxy)

    def style(self):
        """
        ui-split-pane, :host {
            display: flex;
            width: 100%;
            height: 100%;
            overflow: hidden;
            background-color: var(--bg-primary, #ffffff);
        }

        ui-split-pane[direction="vertical"], :host([direction="vertical"]) {
            flex-direction: column;
        }

        ui-split-pane[direction="horizontal"], :host([direction="horizontal"]) {
            flex-direction: row;
        }
        """

    def template(self):
        """
        <div class="ui-split-pane-container" onmousedown="{on_mousedown}" 
             style="display: flex; width: 100%; height: 100%; flex-direction: inherit;">
            <slot></slot>
        </div>
        """
