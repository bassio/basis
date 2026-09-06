"""``@js_component`` — wrap a JS library as a reactive Basis component
(ROADMAP-AMBITIOUS.md Bet 5; plan: JS-COMPONENT-PLAN.md).

Mark any ``Component`` subclass with ``@js_component(module=..., exports=...)`` to turn
it into a JS-backed component:

- The class still renders a normal, SSR-safe template (a deterministic placeholder).
  On the server nothing else happens — SSR output is pure template.
- On the client the ES module is lazily imported once (ref-counted and shared across
  instances via ``basis.client.js_bridge.JsModuleRegistry``), the declared ``exports``
  are exposed as instance attributes, and the wrapper's ``boot_js(module)`` creates the
  JS widget.
- ``sync_js()`` is called whenever a declared ``bridge_props`` field is assigned after
  boot, pushing Python state into JS.
- JS → Python flows through DOM ``CustomEvent``s dispatched on ``__element__`` (via
  ``self.emit(name, detail)``) and caught by ordinary ``on*`` template attributes — the
  standard ``EventBinding``/``py_event`` machinery, exactly like ``onclick`` in any other
  component.

The class may be decorated as a plain ``Component`` (the decorator mixes
:class:`JsComponent` into the MRO *below* the class, so the class's own lifecycle-hook
overrides still win) or inherit :class:`JsComponent` directly. The client-only loader
lives in ``basis.client.js_bridge`` and is imported lazily — never on the server.
"""

from __future__ import annotations

import asyncio
import keyword
from typing import Any, Sequence

from basis.shared.component import Component, IS_CLIENT, in_ssr_hydration

if IS_CLIENT:  # pragma: no cover - client branch (never imported on the server)
    from basis.client.js_bridge import (
        JsModuleRegistry,
        emit_event as _emit_event,
        js_call as _js_call,
        js_new as _js_new,
        log_error as _log_error,
        to_py as _to_py,
        wait_connected as _wait_connected,
    )
else:
    JsModuleRegistry = None  # type: ignore[assignment]


class JsComponentRegistry:
    """Collects every ``@js_component`` class so the server can enumerate the JS
    modules the app depends on (a future ``basis.js_modules`` preload list in
    ``/pyscript.json``). Keyed by tag and by module URL."""

    _by_tag: dict[str, type] = {}
    _by_module: dict[str, set[type]] = {}
    #: stable js_modules name -> module URL (the PyScript ``js_modules.main`` map).
    _name_to_url: dict[str, str] = {}

    @classmethod
    def register(cls, component_cls: type) -> None:
        tag = getattr(component_cls, "__tag__", None)
        module = getattr(component_cls, "__js_module__", None)
        name = getattr(component_cls, "__js_name__", None)
        if tag:
            cls._by_tag[tag] = component_cls
        if module:
            cls._by_module.setdefault(module, set()).add(component_cls)
        if name and module:
            existing = cls._name_to_url.get(name)
            if existing is not None and existing != module:
                raise ValueError(
                    f"@js_component name {name!r} is already used by {existing!r} — "
                    f"pass an explicit unique name= to @js_component."
                )
            cls._name_to_url[name] = module

    @classmethod
    def modules(cls) -> list[str]:
        """Sorted, deduped list of every JS module URL the app references."""
        return sorted(cls._by_module)

    @classmethod
    def js_modules(cls) -> dict[str, str]:
        """Stable ``{name: url}`` map for the PyScript ``js_modules.main`` config."""
        return dict(cls._name_to_url)

    @classmethod
    def classes_for_module(cls, module: str) -> tuple[type, ...]:
        return tuple(cls._by_module.get(module, ()))


class JsComponent(Component):
    """Base for JS-backed components. Prefer the ``@js_component`` decorator.

    Subclasses override the three hooks ``boot_js`` / ``sync_js`` / ``destroy_js`` and
    declare ``bridge_props`` — the fields that, when assigned after boot, trigger
    ``sync_js()``.
    """

    #: ES module URL, resolved against a framework/plugin static mount at runtime.
    __js_module__: str | None = None
    #: Named exports to expose as instance attributes after the module loads.
    __js_exports__: tuple[str, ...] = ()
    #: Stable ``js_modules`` key (PyScript manifest name) for this module.
    __js_name__: str | None = None
    __js_component__: bool = True

    #: Fields that, when assigned after boot, push into JS via ``sync_js()``.
    bridge_props: tuple[str, ...] = ()

    def __init__(self) -> None:
        super().__init__()
        self.__dict__["_js_booted"] = False
        self.__dict__["_js_ready"] = False
        self.__dict__["_js_module"] = None
        self.__dict__["_js_syncing"] = False

    # ── wrapper hooks (override) ────────────────────────────────────────────
    def boot_js(self, module: Any) -> None:
        """Create the JS widget from the imported module namespace.

        e.g. ``self.view = self.js_new(module.EditorView, {...})``. Called once per
        instance on the client, after the module has loaded.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} must implement boot_js(module) — "
            "create the JS widget here."
        )

    def sync_js(self) -> None:
        """Push the current ``bridge_props`` values into the JS widget(s). Called on
        boot and again whenever a bridge prop is assigned after boot."""

    def destroy_js(self) -> None:
        """Tear down the JS widget(s) + any created ``ffi`` proxies."""

    # ── framework-provided helpers ──────────────────────────────────────────
    def js_new(self, ctor: Any, *args: Any) -> Any:
        """Construct a JS object (``ctor.new(*args)``), converting dict/list args via
        ``ffi.to_js`` (the ``AudioRecorder`` pattern). No-op on the server."""
        if not IS_CLIENT:
            return None
        return _js_new(ctor, *args)

    def js_call(self, obj: Any, name: str, *args: Any) -> Any:
        """Call ``obj.name(*args)`` with dict/list args converted for JS. No-op on the
        server."""
        if not IS_CLIENT:
            return None
        return _js_call(obj, name, *args)

    def to_py(self, value: Any) -> Any:
        """Best-effort ``JsProxy.to_py()`` conversion (identity on the server / for
        plain Python values)."""
        if not IS_CLIENT:
            return value
        return _to_py(value)

    def emit(self, name: str, detail: Any = None) -> None:
        """Dispatch a bubbling ``CustomEvent(name, {detail})`` on ``__element__`` —
        caught by a template ``on<name>="{handler}"`` attribute (standard
        ``EventBinding``). No-op on the server."""
        if not IS_CLIENT:
            return
        element = getattr(self, "__element__", None)
        if element is not None:
            _emit_event(element, name, detail)

    # ── lifecycle (framework-owned) ─────────────────────────────────────────
    def on_mounted(self) -> None:
        """Boot the JS widget. On CSR this fires immediately; on SSR pages it is
        deferred so the widget mounts into the live SSR node — visible
        components boot via :meth:`on_hydrated`; hidden-if components (no SSR
        node, so no ``on_hydrated``) boot here once their element connects to
        the live document (when the controlling ``if`` reveals them)."""
        if not IS_CLIENT:
            return
        if in_ssr_hydration():
            self._defer_boot_until_connected()
            return
        self._boot()

    def on_hydrated(self) -> None:
        """SSR-page boot path: after bindings are re-pointed at the live SSR tree."""
        if not IS_CLIENT:
            return
        self._boot()

    def _teardown_js(self) -> None:
        """Teardown of JS subresources, invoked by ``Component.destroy()`` while
        the DOM + event wiring still exist: tear down the JS widget, release the
        module ref and reset the boot flags. (Idempotent — guarded by the
        ``_js_booted`` flag.)"""
        if IS_CLIENT and getattr(self, "_js_booted", False):
            try:
                self.destroy_js()
            except Exception:
                pass
            JsModuleRegistry.unref(self.__js_module__)
        self.__dict__["_js_booted"] = False
        self.__dict__["_js_ready"] = False

    # ── internal ────────────────────────────────────────────────────────────
    def _boot(self) -> None:
        if not IS_CLIENT or getattr(self, "_js_booted", False):
            return
        self.__dict__["_js_booted"] = True
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # no running loop yet — nothing to schedule (server-safe)
        asyncio.ensure_future(self._boot_async())

    def _defer_boot_until_connected(self) -> None:
        """Boot when the element joins the live document (push, no polling).

        On SSR pages every component — including hidden-if children — mounts
        into the detached shadow during ``mount_app_ssr``. Visible components
        get a matching SSR node, so ``on_hydrated`` boots them. Hidden
        components (e.g. a tab the server didn't select) have no SSR node, so
        ``on_hydrated`` never fires and ``on_mounted`` will not re-run when the
        controlling ``if`` later reveals them — booting into the detached
        shadow would mount the widget into a node that dies. The custom
        element's ``connectedCallback`` dispatches a generic ``basis:connected``
        event when the node is (re-)inserted into the live document — exactly
        the reveal moment — so we register a one-shot listener (see
        :func:`basis.client.js_bridge.wait_connected`, which listens on
        ``document`` for the bubbled event and fires when this component's
        element reports ``isConnected``) and boot on it. Idempotent via
        ``_js_booted`` (visible components boot via ``on_hydrated`` first, and
        the JS side stays dumb/agnostic).
        """
        if not IS_CLIENT or getattr(self, "_js_booted", False):
            return
        element = self.__element__
        if element is None:
            return
        _wait_connected(element, self._boot)

    async def _boot_async(self) -> None:
        try:
            module = await JsModuleRegistry.load(self.__js_module__)
        except Exception as exc:
            _log_error(f"@js_component {self.__class__.__name__}: module load failed: {exc}")
            return
        # Destroy-before-boot guard (COMPONENT-LIFECYCLE-PLAN.md P2 §2.3): the
        # instance may have been destroyed while the ES module was loading —
        # destroy() sets _destroyed and clears _js_booted (via _teardown_js).
        # If so, cancel the boot: never call boot_js on a dead node. The module
        # load itself is harmless (cached, ref-counted). Async is single-
        # threaded, so this check right after the await is sufficient.
        if getattr(self, "_destroyed", False) or not getattr(self, "_js_booted", False):
            return
        self.__dict__["_js_module"] = module
        for name in self.__class__.__js_exports__:
            self.__dict__[name] = getattr(module, name, None)
        try:
            self.boot_js(module)
        except Exception as exc:
            _log_error(f"@js_component {self.__class__.__name__}: boot_js failed: {exc}")
            return
        self.__dict__["_js_ready"] = True
        self._sync_bridge()

    def _sync_bridge(self) -> None:
        if getattr(self, "_js_syncing", False):
            return
        self.__dict__["_js_syncing"] = True
        try:
            self.sync_js()
        except Exception as exc:
            _log_error(f"@js_component {self.__class__.__name__}: sync_js failed: {exc}")
        finally:
            self.__dict__["_js_syncing"] = False

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if getattr(self, "_js_ready", False) and name in self.__class__.bridge_props:
            self._sync_bridge()


def _default_js_name(module: str) -> str:
    """Derive a stable ``js_modules`` key from a module URL — the directory
    basename (``/basis/js/chartlib/index.js`` → ``chartlib``). Sanitised to a
    valid Python identifier; authors may pass an explicit ``name=`` instead."""
    path = module.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    segments = [s for s in path.split("/") if s]
    base = segments[-2] if len(segments) >= 2 else (segments[-1] if segments else "jsmodule")
    out = "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in base)
    if not out:
        out = "jsmodule"
    if out[0].isdigit():
        out = "_" + out
    if keyword.iskeyword(out):
        out += "_"
    return out


def js_component(*, module: str, exports: Sequence[str] = (), name: str | None = None):
    """Class decorator: mark a ``Component`` subclass as JS-backed.

    Parameters
    ----------
    module:
        URL of the ES module, relative to a framework/plugin static mount
        (e.g. ``/basis/js/chartlib/index.js``).
    exports:
        Named exports to expose as instance attributes after the module loads.
    name:
        Stable ``js_modules`` key (PyScript manifest name) for this module. Must
        be a valid Python identifier. Defaults to the module URL's directory
        basename (``/basis/js/chartlib/index.js`` → ``chartlib``).

    If the decorated class does not already inherit :class:`JsComponent`, it is
    re-created with ``JsComponent`` mixed into the MRO *below* the class, so any
    lifecycle-hook overrides on the class itself still win.
    """
    def decorator(cls):
        if not issubclass(cls, JsComponent):
            namespace = dict(vars(cls))
            namespace.pop("__dict__", None)
            namespace.pop("__weakref__", None)
            cls = type(cls.__name__, (cls, JsComponent), namespace)
        cls.__js_module__ = module
        cls.__js_exports__ = tuple(exports)
        cls.__js_component__ = True
        cls.__js_name__ = name if name is not None else _default_js_name(module)
        JsComponentRegistry.register(cls)
        return cls
    return decorator
