"""The ``Splitter`` — a drag-to-resize divider between any two Stack children.

The resize primitive's model (compare VS Code/Monaco's ``Sash`` and
``react-resizable-panels``' ``PanelResizeHandle``): the *divider* owns the
interaction — it is the input device that resizes the two flex items on either
side of it. Panes do not know about dividers or siblings; the divider samples
its neighbours' sizes ONCE on ``pointerdown`` and mutates them during
``pointermove``. Keeping the gesture in the in-betweener (rather than a pane) is
what lets any ``Stack`` child be a resizable pane without opt-in, and gives the
drag a single owner.

Smoothness / performance: sizes are sampled once per drag (not per frame);
Pointer Events + ``setPointerCapture`` keep move/up flowing to the divider even
when the pointer leaves it, so there are no global ``window`` listeners and no
per-drag proxy lifecycle; ``touch-action: none`` stops scroll/pinch from
competing with the drag.

Placement: between any two children of a ``Stack``, gated by an ``if=`` binding
conditioned on the adjacent component being resizeable, e.g.::

    <shell-stack direction="row">
        <shell-sidebar side="left" resizeable="{left_resizeable}"></shell-sidebar>
        <shell-splitter if="{left_resizeable}" direction="horizontal"></shell-splitter>
        <shell-main-container></shell-main-container>
    </shell-stack>

The drag handlers are client-only (the server just records them). Siblings whose
host is ``display: contents`` (typical shell parts) are resolved to their real
inner box before resizing.

This is the canonical resize primitive: ``basis.plugins.ui.split_pane``
(``SplitPane`` / ``SplitPaneItem`` / ``SplitHandle``) is slated for deprecation
in favour of ``Stack`` + ``Splitter`` once existing apps migrate (ROADMAP-SHELL.md §5).
"""
from basis.shared.component import Component, IS_CLIENT

if IS_CLIENT:
    from pyscript import window
else:
    window = None


class Splitter(Component):
    """A thin drag-to-resize divider between two Stack children."""

    __tag__ = "shell-splitter"

    # "horizontal" splits left/right (col-resize); "vertical" splits top/bottom (row-resize).
    direction = "horizontal"
    size = "4px"
    min_size = 40  # px — smallest either neighbor may be dragged to

    def __init__(self):
        super().__init__()
        self._dragging = False
        self._prev_box = None
        self._next_box = None
        self._start_pos = 0
        self._start_prev = 0
        self._start_next = 0

    def _sizable_box(self, el):
        """Resolve a sibling to the flex item the splitter actually resizes.

        Shell parts are ``display: contents`` hosts whose inner root is the real
        flex box; plain elements are used as-is. ``el`` may be a Pyodide
        ``JsNull`` proxy when there is no sibling (e.g. resolving from the bar
        instead of its host) — such inputs yield ``None``.
        """
        if el is None or not hasattr(el, "getAttribute"):
            return None
        try:
            display = window.getComputedStyle(el).display
        except Exception:
            display = None
        if display == "contents" and el.firstElementChild is not None:
            return el.firstElementChild
        return el

    def _delta(self, event):
        if self.direction == "horizontal":
            return event.clientX - self._start_pos
        return event.clientY - self._start_pos

    def on_pointer_down(self, event):
        element = self.__element__
        # The component root is the resize bar (the template's single root); the
        # <shell-splitter> host wraps it (the host is display: contents) and the
        # host's siblings are the two panes this divider resizes. Resolve from
        # the host — the bar itself has no siblings (it is the host's only
        # child), so reading them from the bar yields JsNull and crashes.
        host = getattr(element, "parentElement", None)
        if host is None or not hasattr(host, "getAttribute"):
            return
        # Keep move/up flowing to this element even when the pointer leaves it.
        try:
            element.setPointerCapture(event.pointerId)
        except Exception:
            pass

        self._dragging = True
        element.setAttribute("data-dragging", "true")
        # The drag-highlight CSS targets the host (shell-splitter[data-dragging]).
        host.setAttribute("data-dragging", "true")

        self._prev_box = self._sizable_box(host.previousElementSibling)
        self._next_box = self._sizable_box(host.nextElementSibling)
        if self._prev_box is None or self._next_box is None:
            return

        if self.direction == "horizontal":
            self._start_pos = event.clientX
            self._start_prev = self._prev_box.offsetWidth
            self._start_next = self._next_box.offsetWidth
        else:
            self._start_pos = event.clientY
            self._start_prev = self._prev_box.offsetHeight
            self._start_next = self._next_box.offsetHeight

    def on_pointer_move(self, event):
        if not self._dragging or self._prev_box is None or self._next_box is None:
            return

        delta = self._delta(event)
        new_prev = self._start_prev + delta
        new_next = self._start_next - delta
        if new_prev < self.min_size or new_next < self.min_size:
            return

        if self.direction == "horizontal":
            self._prev_box.style.width = f"{new_prev}px"
            self._prev_box.style.flex = "0 0 auto"
            self._next_box.style.width = f"{new_next}px"
            self._next_box.style.flex = "0 0 auto"
        else:
            self._prev_box.style.height = f"{new_prev}px"
            self._prev_box.style.flex = "0 0 auto"
            self._next_box.style.height = f"{new_next}px"
            self._next_box.style.flex = "0 0 auto"

    def on_pointer_up(self, event):
        if not self._dragging:
            return
        self._dragging = False
        element = self.__element__
        if hasattr(element, "removeAttribute"):
            element.removeAttribute("data-dragging")
        host = getattr(element, "parentElement", None)
        if host is not None and hasattr(host, "removeAttribute"):
            host.removeAttribute("data-dragging")
        try:
            element.releasePointerCapture(event.pointerId)
        except Exception:
            pass

    def style(self):
        """
        shell-splitter {
            display: contents;
        }

        .shell-splitter {
            box-sizing: border-box;
            background: var(--border-color, #3a3a52);
            background-clip: padding-box;
            position: relative;
            z-index: 10;
            touch-action: none;  /* pointer events drive the drag, not scroll */
        }

        .shell-splitter[direction="horizontal"] {
            cursor: col-resize;
        }

        .shell-splitter[direction="vertical"] {
            cursor: row-resize;
        }

        .shell-splitter:hover, .shell-splitter[data-dragging="true"] {
            background: var(--accent-color, #007acc);
        }
        """

    def template(self):
        """
        <div class="shell-splitter" direction="{direction}" style="flex: 0 0 {size};" onpointerdown="{on_pointer_down}" onpointermove="{on_pointer_move}" onpointerup="{on_pointer_up}" onpointercancel="{on_pointer_up}"></div>
        """
