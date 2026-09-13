"""Client-only probes for the ``$device`` / ``$network`` context stores.

The stores carry the neutrals the server serialises, so a server-rendered page and a
client-rendered page *first paint* the same thing. This module is the other half: it
reads the real browser **after mount** (so the correction lands identically on both) and
keeps the fields current on resize, rotation, and connectivity changes.

Capability is deliberately not probed: ``hover`` and ``reduced_motion`` are declared
media queries on the store, which the one shared listener per query already answers.

Install once from the client entrypoint (:func:`install_device_probes`). The probes are
released on ``pagehide`` and re-installed on ``pageshow``: a page restored from the
back/forward cache resumes with stale values and, without a release, a second set of
listeners — and that release is what drives the stores' ``on_client_teardown`` hook.
"""

from __future__ import annotations

try:
    from pyscript import window

    PYSCRIPT = True
except ImportError:  # unit tests / import under pytest
    window = None
    PYSCRIPT = False

from basis.shared.device import ensure_device_store
from basis.shared.js import Listener
from basis.shared.network import ensure_network_store
from basis.shared.reactive import batch
from basis.shared.store import Store

#: The observed stores, by name. Looked up rather than imported so teardown and resume
#: never *create* a store that the page did not have.
_CONTEXT_STORES = ("device", "network")

#: Probe bindings: released by :func:`teardown_device_probes`.
_bindings: list[Listener] = []
#: Page-lifecycle bindings: held for the page's lifetime, because they are what
#: re-installs the probes after a restore.
_lifecycle_bindings: list[Listener] = []
_installed = False
_lifecycle_installed = False


def _registered_context_stores() -> list:
    """The context stores this page actually has."""
    found = []
    for name in _CONTEXT_STORES:
        store = Store._registry.get(name)
        if store is not None:
            found.append(store)
    return found


def _probe(event=None) -> None:
    """Read the whole environment once and apply every value that moved.

    Every listener calls this, because an event says the snapshot *may* be stale, not
    which field moved — a connection change can alter ``effectiveType`` alone, and a
    resume can move the viewport and the network at once. Re-reading is cheap precisely
    because the write is skipped when the value did not move (``refrain``), and the
    ``batch`` holds both stores' flushes so one event costs one render.
    """
    if not PYSCRIPT:
        return

    device = ensure_device_store()
    network = ensure_network_store()
    navigator = window.navigator
    # Chromium-only API. Read with a default: a browser without it may hand back a falsy
    # value or raise on the property itself, and neither may cost us the probe.
    connection = getattr(navigator, "connection", None)

    with batch(), device.refrain() as d, network.refrain() as n:
        d.width = int(window.innerWidth)
        d.height = int(window.innerHeight)
        d.dpr = float(window.devicePixelRatio)
        d.touch = navigator.maxTouchPoints > 0
        portrait = window.matchMedia("(orientation: portrait)").matches
        d.orientation = "portrait" if portrait else "landscape"
        d.pointer = "coarse" if window.matchMedia("(pointer: coarse)").matches else "fine"

        n.online = bool(navigator.onLine)
        if connection:
            n.effective_type = str(connection.effectiveType)
            n.save_data = bool(connection.saveData)


def install_device_probes() -> None:
    """Start observing the client environment. Idempotent, and re-reads on every call.

    The page-lifecycle bindings are registered once and outlive
    :func:`teardown_device_probes`, so a back/forward-cache restore can resume.
    """
    global _installed, _lifecycle_installed
    if not PYSCRIPT:
        return

    if not _lifecycle_installed:
        _lifecycle_installed = True
        _lifecycle_bindings.extend(
            [
                Listener(window, "pagehide", _on_pagehide),
                Listener(window, "pageshow", _on_pageshow),
            ]
        )

    if not _installed:
        _installed = True
        _bindings.extend(
            [
                Listener(window, "resize", _probe),
                Listener(window, "orientationchange", _probe),
                Listener(window, "online", _probe),
                Listener(window, "offline", _probe),
                # Chromium-only: a browser without the API binds nothing.
                Listener(getattr(window.navigator, "connection", None), "change", _probe),
            ]
        )

    _probe()


def teardown_device_probes() -> None:
    """Release the probe bindings and the context stores' client state.

    Safe to call repeatedly. The lifecycle bindings stay registered — they are the only
    way back after a restore.
    """
    global _installed
    if not PYSCRIPT:
        return

    _installed = False
    for binding in _bindings:
        binding.dispose()
    _bindings.clear()
    for store in _registered_context_stores():
        try:
            store.on_client_teardown()
        except Exception as e:
            print(f"[Basis] {type(store).__name__}.on_client_teardown failed: {e}")


def _on_pagehide(event=None) -> None:
    """The document is going away (possibly into the back/forward cache): release."""
    teardown_device_probes()


def _on_pageshow(event=None) -> None:
    """The document is live again — after a restore, with stale values and no bindings."""
    if _installed:
        return
    for store in _registered_context_stores():
        try:
            store.on_client_ready()
        except Exception as e:
            print(f"[Basis] {type(store).__name__}.on_client_ready failed: {e}")
    install_device_probes()
