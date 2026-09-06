"""
basis/client/errors_component.py
--------------------------------
The dev-only binding-error overlay as a reactive Basis component.

Previously the overlay was built imperatively (Python -> JS DOM calls) inside
``errors.py``.  It is now a proper component: ``<basis-error-overlay>`` renders
its reactive ``items`` list declaratively (``for`` / ``if`` / ``onclick``
bindings), so new errors appear live, the count badge stays correct, each
entry shows its full detail, and the whole list collapses with a dismiss-all
control.

Plumbing — the error sink, dedup, ``window.__basisErrors``, the ``basis-error``
CustomEvent and SSR replay — stays in ``errors.py``.  This module is purely
presentational.

The class subclasses the *isomorphic* ``Component`` (``basis.shared.component``),
so it is a real client component in the browser and, under pytest, the server
build (which makes its record/handler methods unit-testable without a DOM).

Per-item expand/collapse relies on the framework's loop-owner semantics: the
``onclick`` handlers inside the ``for`` loop run with the overlay (the template
owner) as ``self``, so ``toggle_entry`` can mutate ``self.items`` and re-render.
"""

from basis.shared.component import Component, IS_CLIENT


def _format_detail(err_dict: dict) -> str:
    """Human-readable multi-line detail for one error record."""
    lines = []
    phase = err_dict.get("phase")
    if phase:
        lines.append(f"phase: {phase}")
    line = err_dict.get("template_line")
    if line:
        lines.append(f"template line: {line}")
    error = err_dict.get("error")
    if error:
        lines.append(f"error: {error}")
    hint = err_dict.get("hint")
    if hint:
        lines.append(f"hint: {hint}")
    tb = err_dict.get("traceback")
    if tb:
        lines.append(str(tb))
    return "\n".join(lines)


class ErrorOverlay(Component):
    """Dev-only, fixed-position, collapsible panel listing binding errors.

    The client error sink pushes structured error dicts through :meth:`add`;
    the ``for`` loop re-renders live and ``len(items)`` drives the count badge.
    Each entry's header toggles its detail (``toggle_entry``), the header
    collapses the whole list (``toggle_panel``), and ``✕`` dismisses all (and
    resets the sink's dedup set so a recurring error can be re-shown).
    """

    __tag__ = "basis-error-overlay"

    items = []       # display entries: {key, component, binding_type, expr, detail, expanded}
    collapsed = ""   # "" | "true" — whole-panel collapse

    def __init__(self):
        super().__init__()
        self.items = []
        self.collapsed = ""

    # -- record API (called by the client error sink) ------------------------
    def add(self, err_dict: dict) -> None:
        """Append one error record as a display entry.

        Dedup is owned by the sink in ``errors.py``; this only builds the
        display shape and triggers a reactive re-render.  Entries start
        expanded so detail is visible by default; clicking the header
        collapses them.
        """
        entry = {
            "key": "%s:%s:%s" % (
                err_dict.get("binding_type") or "binding",
                err_dict.get("component") or "?",
                err_dict.get("expr") or "",
            ),
            "component": err_dict.get("component") or "?",
            "binding_type": err_dict.get("binding_type") or "binding",
            "expr": err_dict.get("expr") or "",
            "detail": _format_detail(err_dict),
            "expanded": "true",
        }
        self.items = [*self.items, entry]

    def clear(self) -> None:
        """Dismiss the visible entries (keeps the sink's dedup set)."""
        self.items = []

    def clear_all(self, event=None) -> None:
        """Dismiss all entries and reset the sink's dedup set so a recurring
        error can be re-shown after being dismissed."""
        try:
            from basis.client import errors as _errors
            _errors.clear_seen()
        except Exception:
            pass
        self.items = []

    # -- event handlers -------------------------------------------------------
    def toggle_panel(self, event=None) -> None:
        """Collapse/expand the whole list (clicking the header)."""
        self.collapsed = "" if self.collapsed else "true"

    def toggle_entry(self, event=None) -> None:
        """Expand/collapse ONE entry's detail (clicking its header row).

        Runs on the overlay instance (the loop template owner), so re-assigning
        ``self.items`` re-renders the loop.  The key is read from the clicked
        element's ``data-error-key``, walking up through ancestors so clicking
        a child span still targets the row.
        """
        if event is None:
            return
        curr = getattr(event, "target", None)
        key = None
        while curr is not None:
            if hasattr(curr, "getAttribute"):
                k = curr.getAttribute("data-error-key")
                if k:
                    key = k
                    break
            curr = getattr(curr, "parentNode", None)
        if not key:
            return

        new_items = []
        changed = False
        for entry in self.items:
            if entry.get("key") == key:
                entry = dict(entry)
                entry["expanded"] = "" if entry.get("expanded") else "true"
                changed = True
            new_items.append(entry)
        if changed:
            self.items = new_items

    def dismiss_all(self, event=None) -> None:
        """Dismiss-all button inside the header: stop bubbling so the header's
        toggle handler does not also fire."""
        if event is not None:
            try:
                event.stopPropagation()
            except Exception:
                pass
        self.clear_all()

    def style(self):
        """
        basis-error-overlay {
            display: contents;
        }

        .basis-error-overlay {
            position: fixed;
            top: 12px;
            right: 12px;
            z-index: 2147483646;
            width: 340px;
            max-height: 60vh;
            overflow: auto;
            background: rgba(20, 20, 20, 0.94);
            color: #f8f8f2;
            border: 1px solid #f43f5e;
            border-radius: 8px;
            font: 11px/1.5 system-ui, sans-serif;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        }

        .basis-error-header {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 6px 10px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.12);
            cursor: pointer;
            user-select: none;
        }

        .basis-error-title { font-weight: 600; color: #fda4af; }
        .basis-error-count { margin-left: auto; color: #fda4af; font-weight: 600; }

        .basis-error-dismiss { color: #6b7280; cursor: pointer; padding: 0 2px; }
        .basis-error-dismiss:hover { color: #fda4af; }

        .basis-error-entry {
            border-bottom: 1px solid rgba(255, 255, 255, 0.08);
            padding: 6px 10px;
        }

        .basis-error-entry-head {
            cursor: pointer;
            display: flex;
            gap: 6px;
            align-items: baseline;
        }

        .basis-error-type { color: #c4b5fd; font-weight: 600; }
        .basis-error-component { color: #93c5fd; }
        .basis-error-expr { color: #fbbf24; font-family: monospace; }

        .basis-error-detail {
            margin-top: 4px;
            color: #d1d5db;
            white-space: pre-wrap;
            font-family: monospace;
        }
        """

    def template(self):
        """
        <div class="basis-error-overlay" if="{items}">
            <div class="basis-error-header" onclick="{toggle_panel}">
                <span class="basis-error-title">⚠ Basis errors</span>
                <span class="basis-error-count">{len(items)}</span>
                <span class="basis-error-dismiss" onclick="{dismiss_all}" title="dismiss all">✕</span>
            </div>
            <div class="basis-error-list" if="{not collapsed}">
                <div class="basis-error-entry" for="err" in="{items}" key="key">
                    <div class="basis-error-entry-head" data-error-key="{err['key']}" onclick="{toggle_entry}">
                        <span class="basis-error-type">{err.get('binding_type', '')}</span>
                        <span class="basis-error-component">{err.get('component', '')}</span>
                        <span class="basis-error-expr">{err.get('expr', '')}</span>
                    </div>
                    <div class="basis-error-detail" if="{err.get('expanded')}">
                        <pre>{err.get('detail', '')}</pre>
                    </div>
                </div>
            </div>
        </div>
        """


def mount_error_overlay(container=None):
    """Mount a fresh ``ErrorOverlay`` into *container* (default
    ``document.body``) and ensure its styles are present.  Returns the mounted
    instance.

    Client-only: returns ``None`` outside PyScript so pytest never touches a
    real DOM.
    """
    if not IS_CLIENT:
        return None
    try:
        from pyscript import document
        if container is None:
            container = document.body
        overlay = ErrorOverlay.mount(container)
        style_content = ErrorOverlay._get_style_string()
        if style_content:
            style_el = document.createElement("style")
            style_el.setAttribute("data-component-class", ErrorOverlay.__name__)
            style_el.textContent = style_content
            document.head.appendChild(style_el)
        return overlay
    except Exception:
        return None
