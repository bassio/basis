"""
basis/client/errors.py
----------------------
Client-side structured error reporting.

Installed once by the client entrypoint (``entrypoint.py``)
via :func:`install_error_sink`.  The sink guarantees DOM safety (evaluation
helpers return an empty value rather than a raw ``[Error: ...]`` string) and
surfaces every failure as structured data — ``window.__basisErrors`` plus a
``basis-error`` ``CustomEvent`` — with parity to the hydration report
(``window.__basisHydrationReport`` / ``basis-hydration-mismatch``).

The visual surface is a proper reactive component — ``<basis-error-overlay>``
(``basis/client/errors_component.py``) — mounted automatically when the page
carries the dev marker (``<meta name="basis-mode" content="dev">``, stamped by
the server when running with HMR / ``basis dev``) or when forced via
:func:`set_overlay_enabled`.  This module is the plumbing only: sink, dedup,
global/event dispatch, SSR replay, and overlay mounting.  The component renders
reactively from the records pushed to it (no imperative DOM building here).
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
from basis.client.errors_component import ErrorOverlay, mount_error_overlay

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

    # Drive the reactive overlay component (when mounted) so it re-renders its
    # list live; dedup above keeps a recurring failure from flooding it.
    overlay = _overlay
    if overlay is not None:
        try:
            overlay.add(err_dict)
        except Exception:
            pass

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
# Overlay (reactive component — see errors_component.py)
# ---------------------------------------------------------------------------

def clear_seen() -> None:
    """Reset the dedup set (called by the overlay's dismiss-all control)."""
    global _seen
    _seen = set()


def ensure_overlay():
    """Create (once) the dev error overlay component and mount it into
    ``document.body``.  Returns the mounted :class:`ErrorOverlay` instance, or
    ``None`` when there is no DOM to mount into."""
    global _overlay
    if _overlay is not None:
        return _overlay
    if document is None:
        return None
    _overlay = mount_error_overlay()
    if _overlay is None:
        # Non-PyScript (pytest): keep an instance so callers/tests can drive it;
        # it is simply never mounted into a real DOM.
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
