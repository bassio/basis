"""
basis/client/errors.py
----------------------
Client-side structured error reporting + dev-only overlay.

Installed once by the entrypoints (``entrypoint_csr.py`` / ``entrypoint_ssr.py``)
via :func:`install_error_sink`.  The sink guarantees DOM safety (evaluation
helpers return an empty value rather than a raw ``[Error: ...]`` string) and
surfaces every failure as structured data — ``window.__basisErrors`` plus a
``basis-error`` ``CustomEvent`` — with parity to the hydration report
(``window.__basisHydrationReport`` / ``basis-hydration-mismatch``).

The overlay panel (:class:`ErrorOverlay`) is a dev-only affordance: it is
created when the page carries the dev marker (``<meta name="basis-mode"
content="dev">``, stamped by the server when running with HMR / ``basis dev``)
or when forced via :func:`set_overlay_enabled`.  Each entry shows component,
binding type, expression, template line, and traceback, click-to-expand, with a
dismiss-all control.
"""

from __future__ import annotations

import json as _json

try:
    from pyscript import window, document, ffi

    PYSCRIPT = True
except ImportError:  # unit tests / import under pytest
    window = None
    document = None
    ffi = None
    PYSCRIPT = False

from basis.shared.errors import (
    BindingError,
    ERROR_EVENT,
    ERRORS_GLOBAL,
    set_error_sink,
)

_installed = False
_overlay_override = None
_global_errors: list[dict] = []
_seen: set = set()          # (component, binding_type, expr, error) dedup
_overlay = None


# ---------------------------------------------------------------------------
# Dev-mode gate
# ---------------------------------------------------------------------------

def set_overlay_enabled(value) -> None:
    """Force the overlay on/off.  ``None`` (default) auto-detects from the
    page's dev marker (``<meta name="basis-mode" content="dev">``)."""
    global _overlay_override
    _overlay_override = value


def overlay_enabled() -> bool:
    if _overlay_override is not None:
        return bool(_overlay_override)
    return _read_dev_mode()


def _read_dev_mode() -> bool:
    if document is None:
        return False
    try:
        meta = document.querySelector('meta[name="basis-mode"]')
        if meta is None or not hasattr(meta, "getAttribute"):
            return False
        return (meta.getAttribute("content") or "") == "dev"
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Structural surfacing (global + event) — mirrors _emit_hydration_report
# ---------------------------------------------------------------------------

def _append_to_global(err_dict: dict) -> None:
    _global_errors.append(err_dict)
    if window is None or ffi is None:
        return
    try:
        # Pyodide: window[attr] = list does NOT work; setattr + ffi.to_js does.
        setattr(window, ERRORS_GLOBAL, ffi.to_js(list(_global_errors)))
    except Exception:
        pass


def _dispatch_event(err_dict: dict) -> None:
    if window is None or document is None or ffi is None:
        return
    try:
        detail = ffi.to_js(err_dict)
        event = window.CustomEvent.new(ERROR_EVENT, {"detail": detail, "bubbles": True})
        document.dispatchEvent(event)
    except Exception:
        pass


def _record(err) -> bool:
    """The client error sink: surface a BindingError (or dict) structurally.

    Deduplicates by (component, binding_type, expr, error) so a binding that
    fails on every re-render yields one overlay entry, not a flood.
    """
    if isinstance(err, BindingError):
        err_dict = err.to_dict()
    elif isinstance(err, dict):
        err_dict = err
    else:
        err_dict = {"error": str(err)}

    signature = (
        err_dict.get("component"),
        err_dict.get("binding_type"),
        err_dict.get("expr"),
        err_dict.get("error"),
    )
    if signature in _seen:
        return True
    _seen.add(signature)

    _append_to_global(err_dict)
    _dispatch_event(err_dict)
    try:
        if window is not None and getattr(window, "console", None) is not None:
            window.console.warn(
                "[basis] binding error in %s (%s): %s"
                % (
                    err_dict.get("binding_type") or "binding",
                    err_dict.get("component"),
                    err_dict.get("error"),
                )
            )
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# SSR error replay
# ---------------------------------------------------------------------------

def _replay_server_errors() -> None:
    """Replay server-side (SSR) binding errors serialized in
    ``#basis-initial-state`` (``__basis_errors__``) through the same sink, so
    they surface in the client overlay/global with ``phase: server``."""
    if document is None:
        return
    try:
        script = document.getElementById("basis-initial-state")
        if script is None:
            return
        content = getattr(script, "textContent", None) or getattr(script, "innerText", None)
        if not content:
            return
        state = _json.loads(content)
        for err_dict in state.get("__basis_errors__", []) or []:
            if isinstance(err_dict, dict):
                _record(err_dict)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Overlay
# ---------------------------------------------------------------------------

def _escape_html(text) -> str:
    if not text:
        return ""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _format_detail(err_dict: dict) -> str:
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


class ErrorOverlay:
    """Dev-only, fixed-position, collapsible panel listing every binding error.

    Subscribes to the ``basis-error`` CustomEvent and renders each entry with
    component, binding type, expression, template line, and traceback.
    """

    def __init__(self, document=document, window=window):
        self._document = document
        self._window = window
        self._count = 0
        self._collapsed = False
        self._panel = None
        self._list = None
        self._count_el = None
        self._handler = None
        self._create()
        self._subscribe()

    # -- construction -----------------------------------------------------
    def _create(self):
        if self._document is None:
            return
        panel = self._document.createElement("div")
        panel.id = "basis-error-overlay"
        try:
            panel.style = (
                "position:fixed;top:12px;right:12px;z-index:2147483646;"
                "width:340px;max-height:60vh;overflow:auto;"
                "background:rgba(20,20,20,0.94);color:#f8f8f2;"
                "border:1px solid #f43f5e;border-radius:8px;"
                "font:11px/1.5 system-ui,sans-serif;box-shadow:0 4px 20px rgba(0,0,0,.4)"
            )
        except Exception:
            pass

        header = self._document.createElement("div")
        try:
            header.id = "basis-error-overlay-header"
            header.style = (
                "display:flex;align-items:center;gap:8px;padding:6px 10px;"
                "border-bottom:1px solid rgba(255,255,255,.12);cursor:pointer"
            )
            header.innerHTML = (
                '<span style="font-weight:600;color:#fda4af">⚠ Basis errors</span>'
                '<span id="basis-error-count" style="margin-left:auto;'
                'color:#fda4af;font-weight:600">0</span>'
                '<span style="color:#6b7280;cursor:pointer" title="dismiss all">✕</span>'
            )
        except Exception:
            pass

        list_el = self._document.createElement("div")
        try:
            list_el.id = "basis-error-list"
        except Exception:
            pass

        panel.appendChild(header)
        panel.appendChild(list_el)
        self._document.body.appendChild(panel)

        self._panel = panel
        self._list = list_el
        self._count_el = header
        self._bind_header()

    def _bind_header(self):
        if self._document is None:
            return
        try:
            header = self._document.getElementById("basis-error-overlay-header")
            if header is None or not hasattr(header, "addEventListener"):
                return
            if ffi is not None and hasattr(ffi, "create_proxy"):
                header.addEventListener("click", ffi.create_proxy(self._on_header_click))
        except Exception:
            pass

    def _subscribe(self):
        if self._document is None or not hasattr(self._document, "addEventListener"):
            return
        try:
            handler = self._on_event
            if ffi is not None and hasattr(ffi, "create_proxy"):
                handler = ffi.create_proxy(self._on_event)
            self._document.addEventListener(ERROR_EVENT, handler)
        except Exception:
            pass

    # -- events -----------------------------------------------------------
    def _on_header_click(self, event=None):
        target = getattr(event, "target", None)
        text = ""
        try:
            text = getattr(target, "textContent", "") or ""
        except Exception:
            pass
        if text.strip() == "✕":
            self.clear_all()
        else:
            self._toggle()

    def _on_event(self, event):
        detail = getattr(event, "detail", None)
        if hasattr(detail, "to_py"):
            detail = detail.to_py()
        if isinstance(detail, dict):
            self.add(detail)

    # -- mutations --------------------------------------------------------
    def _toggle(self):
        self._collapsed = not self._collapsed
        if self._list is not None:
            try:
                self._list.hidden = self._collapsed
            except Exception:
                pass

    def add(self, err_dict: dict) -> None:
        """Append one error entry to the panel and update the count."""
        if self._document is None or self._list is None:
            return
        self._count += 1

        entry = self._document.createElement("div")
        try:
            entry.style = "border-bottom:1px solid rgba(255,255,255,.08);padding:6px 10px"
        except Exception:
            pass

        head = self._document.createElement("div")
        try:
            head.style = "cursor:pointer;display:flex;gap:6px;align-items:baseline"
            head.innerHTML = (
                '<span style="color:#c4b5fd;font-weight:600">%s</span>'
                '<span style="color:#93c5fd">%s</span>'
                '<span style="color:#fbbf24;font-family:monospace">%s</span>'
                '<span style="margin-left:auto;color:#6b7280">×</span>'
            ) % (
                _escape_html(err_dict.get("binding_type") or "binding"),
                _escape_html(err_dict.get("component") or "?"),
                _escape_html(err_dict.get("expr") or ""),
            )
        except Exception:
            pass

        detail = self._document.createElement("div")
        try:
            detail.hidden = True
            detail.style = "margin-top:4px;color:#d1d5db;white-space:pre-wrap"
            detail.textContent = _format_detail(err_dict)
        except Exception:
            pass

        try:
            if hasattr(head, "addEventListener") and ffi is not None and hasattr(ffi, "create_proxy"):
                head.addEventListener("click", ffi.create_proxy(lambda e: self._toggle_entry(detail)))
        except Exception:
            pass

        entry.appendChild(head)
        entry.appendChild(detail)
        self._list.appendChild(entry)
        self._update_count()

    @staticmethod
    def _toggle_entry(detail_el):
        try:
            detail_el.hidden = not detail_el.hidden
        except Exception:
            pass

    def clear(self) -> None:
        """Dismiss the visible entries (keeps the dedup set)."""
        if self._list is not None:
            try:
                self._list.replaceChildren()
            except Exception:
                pass
        self._count = 0
        self._update_count()

    def clear_all(self) -> None:
        """Dismiss the visible entries and reset dedup so a recurring error can
        be re-shown after being dismissed."""
        global _seen
        _seen = set()
        self.clear()

    def _update_count(self) -> None:
        if self._document is None:
            return
        try:
            el = self._document.getElementById("basis-error-count")
            if el is not None:
                el.textContent = str(self._count)
        except Exception:
            pass


def ensure_overlay():
    """Create (once) the dev error overlay.  Returns the overlay or None."""
    global _overlay
    if _overlay is None and document is not None:
        _overlay = ErrorOverlay()
    return _overlay


# ---------------------------------------------------------------------------
# Installation
# ---------------------------------------------------------------------------

def install_error_sink():
    """Install the client error sink (idempotent).

    Guarantees DOM safety (evaluation failures record here and render empty),
    replays any SSR errors captured in ``#basis-initial-state``, and creates the
    dev-only overlay when dev mode is active.
    """
    global _installed
    if _installed:
        return _record
    set_error_sink(_record)
    if overlay_enabled():
        ensure_overlay()
    _replay_server_errors()
    _installed = True
    return _record
