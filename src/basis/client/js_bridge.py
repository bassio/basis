"""Client-only runtime for ``@js_component`` — imported lazily, never on the server.

Provides the lazy ES-module loader (a module ``<script>`` that ``import()``s the URL
and stashes the namespace on ``window``), a per-URL ref-counted cache, and the
``js_new`` / ``js_call`` / ``emit_event`` helpers used by ``JsComponent``. Mirrors the
proven ``AudioRecorder`` patterns (``ffi.to_js`` for dict/list args, ``CustomEvent.new``
for emissions).
"""

from __future__ import annotations

import asyncio

from pyscript import window, document, ffi

_LOADED: dict[str, object] = {}
_REFS: dict[str, int] = {}


def log_error(message: str) -> None:
    try:
        window.console.error(f"[basis] {message}")
    except Exception:
        pass


def wait_connected(element, callback) -> None:
    """One-shot: invoke *callback* when *element* connects to the live document.

    Basis custom elements dispatch a generic ``basis:connected`` event from
    their ``connectedCallback`` whenever the node is inserted into the document
    (initial mount, an ``if``-reveal re-insert, hydration-fallback moves). This
    is the push-based complement to Python's ``on_hydrated`` for components that
    were hidden at SSR render time (no SSR node → no ``on_hydrated``; and
    ``on_mounted`` won't re-run when the controlling ``if`` reveals them).

    The event is dispatched on the custom-element host (e.g. ``<ui-chart>``)
    and bubbles *up* from there — it never passes through a component's
    ``__element__`` (the template root, e.g. ``.cm-host``, which is a descendant
    of the host), and at ``on_mounted`` time that root is still detached inside a
    ``DocumentFragment`` with no parent chain to climb. So instead of attaching
    to a specific node, listen on ``document`` for the bubbled event and fire
    when *element* itself reports ``isConnected`` (its host — or an ancestor —
    just joined the live document). If *element* is already connected at
    registration, *callback* runs synchronously. Returns a no-arg disposer; the
    listener is one-shot and removed after firing.
    """
    if element is None:
        callback()
        return lambda: None
    try:
        if getattr(element, "isConnected", False):
            callback()
            return lambda: None
    except Exception:
        pass

    def _on_connected(_event):
        try:
            connected = bool(getattr(element, "isConnected", False))
        except Exception:
            connected = False
        if not connected:
            return  # some other element connected; ours is still detached
        try:
            document.removeEventListener("basis:connected", proxy)
        except Exception:
            pass
        callback()

    proxy = ffi.create_proxy(_on_connected)
    document.addEventListener("basis:connected", proxy)

    def _dispose():
        try:
            document.removeEventListener("basis:connected", proxy)
        except Exception:
            pass
        try:
            proxy.destroy()
        except Exception:
            pass

    return _dispose


def wait_disconnected(element, callback) -> None:
    """One-shot: invoke *callback* the first time *element* leaves the live
    document.

    Mirror of :func:`wait_connected` for the disconnect direction. Basis custom
    elements dispatch a generic ``basis:disconnected`` event when they — or an
    ancestor subtree containing them — are removed from the document. A removed
    node cannot bubble its own event up to ``document`` (it is already
    detached), so ``disconnectedCallback`` dispatches directly on ``document``;
    this helper therefore also listens on ``document`` and fires when *element*
    reports ``isConnected == False`` (its host — or an ancestor — just left the
    live document).

    Unlike :func:`wait_connected` there is deliberately NO synchronous-fire
    path for "already disconnected": a component staged in the detached SSR
    shadow is also ``isConnected == False`` but has not *disconnected* — it is
    about to connect. The callback fires only on a real connected →
    disconnected transition. Returns a no-arg disposer; the listener is one-shot
    and removed after firing.
    """
    if element is None:
        callback()
        return lambda: None

    def _on_disconnected(_event):
        try:
            connected = bool(getattr(element, "isConnected", False))
        except Exception:
            connected = True
        if connected:
            return  # some other element disconnected; ours is still in the doc
        try:
            document.removeEventListener("basis:disconnected", proxy)
        except Exception:
            pass
        callback()

    proxy = ffi.create_proxy(_on_disconnected)
    document.addEventListener("basis:disconnected", proxy)

    def _dispose():
        try:
            document.removeEventListener("basis:disconnected", proxy)
        except Exception:
            pass
        try:
            proxy.destroy()
        except Exception:
            pass

    return _dispose


class JsModuleRegistry:
    """Ref-counted cache of imported JS module namespaces, keyed by URL."""

    @classmethod
    def get(cls, url: str):
        return _LOADED.get(url)

    @classmethod
    async def load(cls, url: str):
        """Import *url* once; subsequent calls share the cached namespace.

        Fast path: if *url* is declared in the page manifest's ``js_modules.main``,
        PyScript has already loaded it at boot — return ``pyscript.js_modules.<name>``
        instead of injecting a dynamic ``import()``. Falls back to the lazy loader
        for modules that were not preloaded (e.g. dynamically contributed
        components on a page that didn't declare them).
        """
        if url in _LOADED:
            _REFS[url] = _REFS.get(url, 0) + 1
            return _LOADED[url]
        module = cls._preloaded(url)
        if module is None:
            module = await _import_module(url)
        if module is None:
            raise RuntimeError(f"JS module failed to load: {url}")
        _LOADED[url] = module
        _REFS[url] = 1
        return module

    @classmethod
    def _preloaded(cls, url: str):
        """Return the already-loaded module namespace for *url* if PyScript's
        ``js_modules`` preloaded it, else ``None``."""
        name = None
        try:
            from pyscript import config
            name = ((config.get("js_modules") or {}).get("main") or {}).get(url)
        except Exception:
            return None
        if not name:
            return None
        try:
            from pyscript import js_modules as _mods
        except Exception:
            try:
                import pyscript as _pyscript
                _mods = getattr(_pyscript, "js_modules", None)
            except Exception:
                _mods = None
        if _mods is None:
            return None
        return getattr(_mods, name, None)

    @classmethod
    def unref(cls, url: str | None) -> None:
        if not url or url not in _REFS:
            return
        _REFS[url] -= 1
        if _REFS[url] <= 0:
            _LOADED.pop(url, None)
            _REFS.pop(url, None)


async def _import_module(url: str):
    """Load an ES module once and return its namespace proxy (or None on failure).

    A module ``<script>`` is injected with a dynamic ``import()``; when it settles the
    namespace is stashed on ``window`` under a slot name and a load event is fired.
    The promise path means a 404 / syntax error is caught (never an unhandled
    rejection), and the timeout bounds the wait.
    """
    slot = f"__basis_js_{abs(hash(url))}"
    future = asyncio.get_running_loop().create_future()
    escaped = url.replace("\\", "\\\\").replace("'", "\\'")

    script = document.createElement("script")
    script.type = "module"
    script.textContent = (
        f'import("{escaped}")'
        f".then(m => {{ window['{slot}'] = m; }})"
        f".catch(e => {{ window['{slot}'] = null; "
        f"console.error('[basis] js_component module load failed:', e); }})"
        f".finally(() => window.dispatchEvent(new CustomEvent('{slot}:loaded')));"
    )
    document.head.appendChild(script)

    def _on_loaded(_event):
        if not future.done():
            future.set_result(getattr(window, slot, None))

    proxy = ffi.create_proxy(_on_loaded)
    window.addEventListener(f"{slot}:loaded", proxy)
    try:
        await asyncio.wait_for(future, timeout=15)
        return future.result()
    except asyncio.TimeoutError:
        log_error(f"timed out loading JS module: {url}")
        return None
    finally:
        window.removeEventListener(f"{slot}:loaded", proxy)
        proxy.destroy()


def _to_js_arg(value):
    if isinstance(value, dict):
        return ffi.to_js(value)
    if isinstance(value, (list, tuple)):
        return ffi.to_js(list(value))
    return value


def js_new(ctor, *args):
    """Construct a JS object: ``ctor.new(*args)`` with dict/list args converted via
    ``ffi.to_js`` (the ``AudioRecorder`` pattern)."""
    return ctor.new(*(_to_js_arg(a) for a in args))


def js_call(obj, name: str, *args):
    fn = getattr(obj, name)
    return fn(*(_to_js_arg(a) for a in args))


def to_py(value):
    to_py = getattr(value, "to_py", None)
    if callable(to_py):
        try:
            return to_py()
        except Exception:
            return value
    return value


def emit_event(element, name: str, detail=None) -> None:
    """Dispatch a bubbling ``CustomEvent`` on *element* — the ``AudioRecorder`` form."""
    detail = detail if detail is not None else {}
    event = window.CustomEvent.new(name, ffi.to_js({"detail": detail, "bubbles": True}))
    element.dispatchEvent(event)
