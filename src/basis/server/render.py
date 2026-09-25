"""
basis/server/render.py
----------------------
Server-side page rendering pipeline (SSR + CSR) for Basis + FastAPI.

The single canonical entry is :func:`render_page`, which dispatches on the page
class to one of three private engines:

* ``_render_page_static`` — renders a page that never boots a client (a
  ``StaticPage``): the same stores, request hooks and server-side mount as SSR,
  with nothing serialized and nothing stamped.
* ``_render_page_ssr`` — server-renders the page *and* its root component
  (server_load, hydration IDs, serialized initial state), then calls
  ``Page._render``.
* ``_render_page_csr`` — sends the client-rendered shell plus the serialized
  initial state; the unified client entrypoint mounts the root component.

Every engine ends in ``Page._render`` (→ shell assembly), the single
server-side funnel every rendered page passes through. The blessed public
serving API is
``PageResponse.from_page`` (``basis.server.responses``); ``render_page`` is the
lower-level render function it wraps, and the route decorators (``@app.serve``,
``@app.page``, ``app.include_page``) build on both.
"""

from __future__ import annotations
import asyncio
import inspect
import json
import logging

from typing import Any

from fastapi import Request

from basis.server.db import RequestDBSession
from basis.shared.context import request_var
from basis.shared.store import (
    FRAMEWORK_STORE_NAMES,
    Store,
    attach_app_to_store,
    run_apply_request,
)
from basis.shared.base_component import BaseComponent
from basis.shared.errors import ErrorCollector
from basis.shared.serialization import json_dumps_script_safe


logger = logging.getLogger(__name__)


def _attach_app_to_store_bound_stores(all_stores, request_app):
    """Attach the request app to app-bound stores (``_requires_app``) and
    refresh their projection so components render and serialization see current
    app state. Called both inside ``_get_all_stores`` (global/page stores) and
    over the whole registry in ``_render_page_ssr`` (stores swept in later, e.g.
    when a caller renders a Page directly without ``global_stores``)."""
    if request_app is None:
        return
    from basis.shared.store import attach_app_to_store
    for store in all_stores.values():
        attach_app_to_store(store, request_app)


def _get_all_stores(
    page_cls,
    root_component_cls,
    stores: dict | None = None,
    global_stores: list | None = None,
    request_app=None
) -> dict[str, Store]:
    """Collect all stores from Page, Component, and global configurations.

    Stores are reconstructed from their persistent blueprint when one exists, so
    SSR serializes the *proper subclass with its constructor state* (e.g. a
    ``CounterStore`` with ``count=0``).  A plain ``Store(name)`` is only created
    as a fallback when no blueprint was ever recorded (config-only stores).
    """
    all_stores = stores or {}
    from basis.shared.base_component import _effective_store_inclusions
    for cls in [page_cls, root_component_cls]:
        for cfg in _effective_store_inclusions(cls):
                name = cfg.name
                if name not in all_stores:
                    if name not in Store._registry:
                        store = Store.reinstantiate(name) or Store(name)
                        Store._registry[name] = store
                    else:
                        store = Store._registry[name]
                    all_stores[name] = store

    if global_stores:
        for cfg in global_stores:
            name = cfg['name']
            if name not in all_stores:
                if name not in Store._registry:
                    store = Store.reinstantiate(name) or Store(name)
                    Store._registry[name] = store
                else:
                    store = Store._registry[name]
                all_stores[name] = store

    # App-bound stores (e.g. PluginRegistryStore) opt in via a ``_requires_app``
    # class attr; attach the request's app so they can project app-global state
    # (e.g. plugin registrations) at serialize time.
    _attach_app_to_store_bound_stores(all_stores, request_app)
    return all_stores


def _collect_stores(request, page_cls, root_component_cls, global_stores) -> dict[str, Store]:
    """Every store this request renders from.

    ``Page._load`` has already instantiated the page's declared store subset (or
    every auto-discovered blueprint when the page declares none), so sweeping the
    registry afterwards picks up everything the page mounts with — including
    stores created by a hand-rolled route that never passed ``global_stores``.

    Framework control-plane stores are then forced in: they hydrate on every page
    regardless of the page's ``Page.stores`` subset, and the per-request registry
    clear means they may need reconstructing from their blueprint. Both engines
    collect through here, so SSR and CSR hydrate from the same set.
    """
    all_stores = _get_all_stores(
        page_cls, root_component_cls, None, global_stores, request_app=request.app
    )
    for name, store in Store._registry.items():
        all_stores.setdefault(name, store)
    for name in FRAMEWORK_STORE_NAMES:
        if name not in all_stores:
            all_stores[name] = Store._registry.get(name) or Store.resolve(name)
    return all_stores


async def _run_store_request_hooks(request, stores) -> None:
    """Attach the request app to app-bound stores and run their per-request hooks.

    ``apply_request(request)`` is the generic hook a store opts into when its state
    depends on the request (``$theme`` reads its ``basis_theme`` cookie; an auth
    store resolves its session cookie). Runs before anything reads store state, so
    components and the serialized initial state agree.
    """
    for store in stores:
        attach_app_to_store(store, request.app)
    for store in stores:
        await run_apply_request(store, request)


def _serialize_initial_state(all_stores: dict[str, Store], errors=None) -> str:
    """Serialize the current state of all collected stores.

    ``errors`` (an :class:`~basis.shared.errors.ErrorCollector` or None) is
    serialized under the reserved ``__basis_errors__`` key so the client overlay
    can surface server-side (SSR) binding-evaluation failures.
    """
    initial_state: dict[str, Any] = {}
    for store_name, store_instance in all_stores.items():
        initial_state[store_name] = store_instance.serialize()

    ssr_params = {}
    ssr_url = {}

    for store_name, store_instance in all_stores.items():
        params = getattr(store_instance, '_ssr_params', None)
        if params is not None:
            ssr_params[store_name] = params

        url = getattr(store_instance, '_ssr_url', None)
        if url is not None:
            ssr_url[store_name] = url

    basis_meta = {}
    if ssr_params:
        basis_meta["ssr_params"] = ssr_params
    if ssr_url:
        basis_meta["ssr_url"] = ssr_url

    if basis_meta:
        initial_state["__basis_meta__"] = basis_meta

    if errors is not None and not errors.is_empty:
        initial_state["__basis_errors__"] = errors.to_dict()

    # Script-safe JSON: the page template escapes interpolated text, and
    # <script> content is not entity-decoded, so `<`/`>`/`&` must be \uXXXX.
    return json_dumps_script_safe(initial_state, indent=2)


def _development_mode(request: Request) -> bool:
    return bool(getattr(getattr(request, "app", None), "_start_hmr_watcher", False))


def _report_render_errors(errors: ErrorCollector) -> None:
    for error in errors.errors:
        logger.error(
            "Binding evaluation failed during render: component=%s binding=%s "
            "expr=%r error=%s",
            error.component,
            error.binding_type,
            error.expr,
            error.error,
        )


def _resolve_render_mode(page_cls, render_mode: str | None) -> str:
    """Resolve how a page should be rendered.

    Precedence: an explicit ``render_mode`` argument > the page class's
    ``render_mode``. The base ``Page.render_mode`` default is ``"ssr"``.
    """
    if render_mode is not None:
        return render_mode
    return page_cls.render_mode


async def render_page(
    request: Request,
    page_cls=None,
    *,
    render_mode: str | None = None,
    global_stores: list | None = None,
) -> str:
    """Render *page_cls* to a full HTML document.

    The page class selects the pipeline: a ``StaticPage`` subclass (``hydrates =
    False``) renders server-side only and refuses an explicit ``render_mode``; a
    ``Page`` subclass resolves ``render_mode`` — the argument → an explicit
    ``Page.render_mode`` class override → ``"ssr"`` — and renders through the SSR
    or CSR engine.

    ``root_component`` is read from ``page_cls`` (``None`` = no reactive root); it may
    also be passed explicitly to ``_render_page_ssr`` as an escape hatch.

    Prefer ``PageResponse.from_page`` for FastAPI endpoints — it wraps this in a
    response with status/headers.
    """
    # The in-flight request is reachable from any plugin code the render runs —
    # store hooks, components, their helpers — via ``current_request()``.
    token = request_var.set(request) if request is not None else None
    error_collector = ErrorCollector()
    try:
        with error_collector:
            if not getattr(page_cls, "hydrates", True):
                from basis.shared.page import refuse_static_render_mode

                refuse_static_render_mode(page_cls, render_mode)
                # The request's database session is bound here for the static engine too:
                # ``apply_request`` hooks and ``server_load`` query it.
                async with RequestDBSession(request):
                    result = await _render_page_static(
                        request, page_cls, global_stores=global_stores
                    )
            else:
                mode = _resolve_render_mode(page_cls, render_mode)
                if mode not in ("ssr", "csr"):
                    raise ValueError(f"render_mode must be 'ssr' or 'csr', got {mode!r}")
                # The request's database session is bound here — the single dispatch
                # entry, wrapping both engines — so it is established before any store
                # hook runs, in one place rather than once per engine.
                async with RequestDBSession(request):
                    if mode == "ssr":
                        result = await _render_page_ssr(
                            request,
                            page_cls,
                            global_stores=global_stores,
                            errors=error_collector,
                        )
                    else:
                        result = await _render_page_csr(
                            request,
                            page_cls,
                            global_stores=global_stores,
                            errors=error_collector,
                        )
        return result
    finally:
        _report_render_errors(error_collector)
        if token is not None:
            request_var.reset(token)


async def _render_page_static(
    request: Request,
    page_cls=None,
    *,
    global_stores: list | None = None,
) -> str:
    """Render a page that never boots a client (a ``StaticPage``).

    The same request pipeline as the SSR engine — the per-request store registry, the
    ``apply_request`` hooks, the declarative root mount and its ``server_load`` — with
    the two client-only steps dropped: nothing is serialized into an initial state and
    no hydration surface is stamped. The document therefore carries exactly what the
    server resolved while rendering it.

    Internal — use ``render_page`` / ``PageResponse.from_page``.
    """
    from basis.shared.router import Route

    root_component = getattr(page_cls, "root_component", None)

    # Reset global registries to isolate per-request SSR state (see _render_page_ssr).
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    Route._route_registry.clear()

    page_instance = page_cls._load(request=request)

    # Keep the router's current path in sync with the request URL.
    router_store = Store._registry.get("router")
    if router_store is not None and hasattr(request, "url"):
        router_store.current_path = request.url.path

    all_stores = _collect_stores(request, page_cls, root_component, global_stores)
    await _run_store_request_hooks(request, all_stores.values())

    all_components = []
    app = page_instance.mount_root_app() if root_component is not None else None
    if app is not None:
        all_components.append(app)
        for child_binding in app.get_child_bindings(recursive=True):
            all_components.append(child_binding.childinstance)
        for provider in getattr(app, "_mounted_providers", ()):
            if provider not in all_components:
                all_components.append(provider)

    preload_tasks = [
        comp.server_load()
        for comp in all_components
        if inspect.iscoroutinefunction(getattr(comp, "server_load", None))
    ]
    if preload_tasks:
        await asyncio.gather(*preload_tasks)

    return page_instance._render(request)


async def _render_page_ssr(
    request: Request,
    page_cls=None,
    *,
    root_component=None,
    global_stores: list | None = None,
    errors: ErrorCollector,
) -> str:
    """Server-side render a Page (and its root component) to a full HTML document.

    The SSR engine: mounts the root component server-side, runs ``server_load``
    hooks, applies hydration IDs, serializes the initial state, then delegates
    the shell assembly to ``Page.render``. Internal — use ``render_page`` /
    ``PageResponse.from_page``.
    """
    from basis.shared.page import Page as PageBase
    from basis.shared.router import Route

    if page_cls is None:
        page_cls = PageBase

    if root_component is None:
        root_component = getattr(page_cls, "root_component", None)

    title = getattr(page_cls, "title", "Basis App")
    entry_module = getattr(page_cls, "entry_module", "/basis/client/entrypoint.py")
    pyscript_src = getattr(page_cls, "pyscript_src", "/pyscript")
    # The default "/pyscript" means "the framework's offline bundle", which is
    # served at a content-addressed /pyscript/<fingerprint> root (immutable
    # caching) — expand it here so the shell references the versioned URLs.
    if pyscript_src == "/pyscript":
        from basis.server.static import offline_pyscript_url

        pyscript_src = offline_pyscript_url()

    # Reset global registries to isolate per-request SSR state and avoid DetachedInstanceError
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    Route._route_registry.clear()

    # 1. Setup Page instance
    page_instance = page_cls._load(request=request)
    page_instance.render_mode = "ssr"
    page_instance.title = title
    page_instance.entry_module = entry_module
    page_instance.pyscript_src = pyscript_src

    # Keep the router's current path in sync with the request URL.
    router_store = Store._registry.get("router")
    if router_store is not None and hasattr(request, "url"):
        router_store.current_path = request.url.path

    # 2. Collect every store this request renders from. The request's database
    #    session is already bound by ``render_page``, above both engines, so a
    #    per-request hook may query the database (an auth store resolving its
    #    session cookie) from its first line.
    all_stores = _collect_stores(request, page_cls, root_component, global_stores)

    # 3. Request-pref hooks: a store may opt in by defining
    #    ``apply_request(request)`` to read a persisted pref (e.g. ``$theme``'s
    #    ``basis_theme`` cookie) so the SSR first paint is already themed — no
    #    flash of the default theme. Runs before mount so components render
    #    against the request's applied state.
    await _run_store_request_hooks(request, all_stores.values())

    # 4. The root app mounts inside the Page's own <body> region via
    #    Page.mount_root_app() — no engine-side mount-region
    #    lookup is needed; the Page locates its <body> itself.

    # 5. Mount the root component (if any — static pages have none).
    #    The Page owns its root as a nested ChildBinding under a hyphenated
    #    host tag in its <body> app slot ("the root is just another
    #    component"). Every page root gets a host tag — the root's declared
    #    hyphenated __tag__ or one kebab-derived from its class name — so all
    #    boot paths (real Page subclasses AND synthesized @app.page shells)
    #    unify here. Component styles live in-tree in the <head> (every Page
    #    renders the component_style_items loop), so nothing is re-injected.
    mounted_apps = []
    if root_component is not None:
        app = page_instance.mount_root_app()
        if app is not None:
            mounted_apps.append(app)

    # 6. Collect every component for the server_load preload phase
    all_components = []
    for app in mounted_apps:
        child_bindings = list(app.get_child_bindings(recursive=True))
        child_components = [cb.childinstance for cb in child_bindings]
        all_components.extend([app] + child_components)
        if hasattr(app, '_mounted_providers'):
            for provider in app._mounted_providers:
                if provider not in all_components:
                    all_components.append(provider)

    # 7. Run server_load hooks concurrently; re-check stores created by them
    preload_tasks = []
    for comp in all_components:
        if hasattr(comp, 'server_load') and inspect.iscoroutinefunction(comp.server_load):
            preload_tasks.append(comp.server_load())

    if preload_tasks:
        await asyncio.gather(*preload_tasks)

        for store_name, store_instance in Store._registry.items():
            if store_name not in all_stores:
                all_stores[store_name] = store_instance

    # 8. Final render: serialize all stores into the initial state
    for store_name, store_instance in Store._registry.items():
        if store_name not in all_stores:
            all_stores[store_name] = store_instance
    initial_state_json = _serialize_initial_state(
        all_stores, errors=errors if _development_mode(request) else None
    )

    # Whole-page hydration (HYDRATION-WHOLEPAGE.md No.2 / Option A): stamp the
    # Page's OWN hydration surface (head h: + body b:) right here, passing the
    # declaratively-mounted body app into the b: walk — the served SSR document
    # then carries the whole head+body surface the client keeps alive. CSR
    # leaves this off (its head is served static).
    html = page_instance._render(
        request,
        initial_state_json=initial_state_json,
        stamp_hydration=True,
        body_app=(mounted_apps[0] if mounted_apps else None),
    )
    final_state_json = _serialize_initial_state(
        all_stores, errors=errors if _development_mode(request) else None
    )
    if final_state_json != initial_state_json:
        page_instance.initial_state_json = final_state_json
        html = page_instance._serialize_document()
    return html


async def _render_page_csr(
    request: Request,
    page_cls=None,
    *,
    global_stores: list | None = None,
    errors: ErrorCollector,
) -> str:
    """Client-side-rendered shell: the page shell plus the serialized initial
    state; the unified client entrypoint mounts the root component.

    Uses the same store pipeline as ``_render_page_ssr`` — same collection, same
    per-request hooks, same DB session, same serializer — minus the server-side
    mount and ``server_load`` phase. The two engines therefore hydrate from
    identical state, so a store's request-time projection cannot depend on the
    render mode.

    Internal — use ``render_page`` / ``PageResponse.from_page``.
    """
    page_instance = page_cls._load(request=request)
    # Same default expansion as the SSR engine: the shell's core.js/css
    # point at the content-addressed offline bundle root.
    if getattr(page_instance, "pyscript_src", None) == "/pyscript":
        from basis.server.static import offline_pyscript_url

        page_instance.pyscript_src = offline_pyscript_url()
    page_instance.render_mode = "csr"

    root_component = getattr(page_cls, "root_component", None)
    all_stores = _collect_stores(request, page_cls, root_component, global_stores)
    await _run_store_request_hooks(request, all_stores.values())
    initial_state_json = _serialize_initial_state(
        all_stores, errors=errors if _development_mode(request) else None
    )

    html = page_instance._render(request, initial_state_json=initial_state_json)
    final_state_json = _serialize_initial_state(
        all_stores, errors=errors if _development_mode(request) else None
    )
    if final_state_json != initial_state_json:
        page_instance.initial_state_json = final_state_json
        html = page_instance._serialize_document()
    return html
