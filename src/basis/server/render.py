"""
basis/server/render.py
----------------------
Server-side page rendering pipeline (SSR + CSR) for Basis + FastAPI.

The single canonical entry is :func:`render_page`, which resolves
``render_mode`` and dispatches to one of the two private engines:

* ``_render_page_ssr`` — server-renders the page *and* its root component
  (server_load, hydration IDs, serialized initial state), then calls
  ``Page.render``.
* ``_render_page_csr`` — sends the client-rendered shell plus the serialized
  initial state; the unified client entrypoint mounts the root component.

Both engines end in ``Page.render`` (→ shell assembly), the single server-side
funnel every rendered page passes through. The blessed public serving API is
``PageResponse.from_page`` (``basis.server.responses``); ``render_page`` is the
lower-level render function it wraps, and the route decorators (``@app.serve``,
``@app.page``, ``app.include_page``) build on both.
"""

from __future__ import annotations
import asyncio
import json

from typing import Any

from fastapi import Request

from basis.shared.store import Store
from basis.shared.base_component import BaseComponent
from basis.shared.hydration import apply_hydration_to_component
from basis.shared.errors import ErrorCollector, get_error_sink, set_error_sink
from basis.shared.serialization import json_dumps_script_safe


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
    for cls in [page_cls, root_component_cls]:
        if hasattr(cls, '__basis_stores__'):
            for cfg in cls.__basis_stores__:
                name = cfg['name']
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


def _apply_hydration_logic(app, root_component_plus_child_components):
    """Apply hydration IDs and component IDs to the DOM tree.

    Delegates to the shared set-based algorithm in ``shared/hydration.py``,
    which also stamps ``data-basis-text`` text ordinals.
    """
    apply_hydration_to_component(app, root_component_plus_child_components)


def _resolve_render_mode(page_cls, render_mode: str | None) -> str:
    """Resolve how a page should be rendered.

    Precedence: an explicit ``render_mode`` argument > a ``render_mode`` the
    page class explicitly overrides on itself > ``"ssr"`` (the default for
    page-serving). The base ``Page.render_mode = "csr"`` default only applies to
    the legacy direct ``Page.load()`` + ``Page.render()`` path (deprecated).
    """
    if render_mode is not None:
        return render_mode
    explicit = getattr(page_cls, "__dict__", {}).get("render_mode")
    if explicit is not None:
        return explicit
    return "ssr"


async def render_page(
    request: Request,
    page_cls=None,
    *,
    render_mode: str | None = None,
    global_stores: list | None = None,
) -> str:
    """Render *page_cls* to a full HTML document.

    This is the single canonical server-side render entry. ``render_mode``
    selects the pipeline: ``"ssr"`` (default) server-renders the page and its
    root component; ``"csr"`` sends the client-rendered shell + serialized
    initial state. Resolution order: the ``render_mode`` argument → an explicit
    ``Page.render_mode`` class override → ``"ssr"``.

    ``root_component`` is read from ``page_cls`` (``None`` = static page); it may
    also be passed explicitly to ``_render_page_ssr`` as an escape hatch.

    Prefer ``PageResponse.from_page`` for FastAPI endpoints — it wraps this in a
    response with status/headers.
    """
    mode = _resolve_render_mode(page_cls, render_mode)
    if mode == "ssr":
        return await _render_page_ssr(request, page_cls, global_stores=global_stores)
    if mode == "csr":
        return _render_page_csr(request, page_cls, global_stores=global_stores)
    raise ValueError(f"render_mode must be 'ssr' or 'csr', got {mode!r}")


async def _render_page_ssr(
    request: Request,
    page_cls=None,
    *,
    root_component=None,
    global_stores: list | None = None,
) -> str:
    """Server-side render a Page (and its root component) to a full HTML document.

    The SSR engine: mounts the root component server-side, runs ``server_load``
    hooks, applies hydration IDs, serializes the initial state, then delegates
    the shell assembly to ``Page.render``. Internal — use ``render_page`` /
    ``PageResponse.from_page``.
    """
    from basis.shared.page import Page as PageBase, _set_render_pipeline
    from basis.shared.router import Route

    if page_cls is None:
        page_cls = PageBase

    if root_component is None:
        root_component = getattr(page_cls, "root_component", None)

    title = getattr(page_cls, "title", "Basis App")
    entry_module = getattr(page_cls, "entry_module", "/basis/client/entrypoint.py")
    pyscript_src = getattr(page_cls, "pyscript_src", "/pyscript")

    # Reset global registries to isolate per-request SSR state and avoid DetachedInstanceError
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    Route._route_registry.clear()

    # Suppress the load()/render() deprecation warnings for our internal calls.
    _set_render_pipeline(True)
    try:
        # 1. Setup Page instance
        page_instance = page_cls.load(request=request)
        page_instance.render_mode = "ssr"
        page_instance.title = title
        page_instance.entry_module = entry_module
        page_instance.pyscript_src = pyscript_src

        # Keep the router's current path in sync with the request URL.
        router_store = Store._registry.get("router")
        if router_store is not None and hasattr(request, "url"):
            router_store.current_path = request.url.path

        # 2. Collect stores
        all_stores = _get_all_stores(
            page_cls, root_component, None, global_stores, request_app=request.app
        )

        # Attach the request app to any app-bound store already in the registry
        # (Page.load creates every blueprint store; a caller that renders a Page
        # directly without ``global_stores`` only picks them up via the later
        # registry sweep — attach here so components render a refreshed projection).
        _attach_app_to_store_bound_stores(Store._registry, request.app)

        # Request-pref hook: a store may opt in by defining ``apply_request(request)``
        # to read a persisted pref (e.g. ``$theme``'s ``basis_theme`` cookie) so the
        # SSR first paint is already themed — no flash of the default theme.
        for store in Store._registry.values():
            apply_request = getattr(store, "apply_request", None)
            if callable(apply_request):
                try:
                    apply_request(request)
                except Exception:
                    pass

        # 3. Locate the SSR mount point in the page shell
        basis_ssr_root = None
        for node in page_instance.__element__.descendants:
            if hasattr(node, 'getAttribute') and node.getAttribute('id') == 'basis-ssr-root':
                basis_ssr_root = node
                break
        if basis_ssr_root is None:
            basis_ssr_root = page_instance.__element__.children[1]

        # 4. Optional DB session for the request (DBAppMixin apps)
        session_token = None
        session_generator = None
        if hasattr(request, "app") and hasattr(request.app, "get_session") and request.app.get_session is not None:
            import inspect
            from basis.shared.context import db_session_var
            get_session_func = request.app.get_session

            if inspect.isgeneratorfunction(get_session_func):
                session_generator = get_session_func()
                try:
                    db_session = next(session_generator)
                except StopIteration:
                    db_session = None
            else:
                db_session = get_session_func()

            if db_session is not None:
                session_token = db_session_var.set(db_session)

        # Collect every binding-evaluation error raised during this SSR render so
        # it can be surfaced in the client overlay.  With the sink installed,
        # safe_eval returns an empty value instead of "[Error: ...]".
        error_collector = ErrorCollector()
        _prev_sink = get_error_sink()
        set_error_sink(error_collector)
        try:
            # 5. Mount the root component (if any — static pages have none)
            mounted_apps = []
            if root_component is not None:
                mounted_apps.append(root_component.mount_app(basis_ssr_root, replace=False))

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
                if hasattr(comp, 'server_load') and asyncio.iscoroutinefunction(comp.server_load):
                    preload_tasks.append(comp.server_load())

            if preload_tasks:
                await asyncio.gather(*preload_tasks)

                for store_name, store_instance in Store._registry.items():
                    if store_name not in all_stores:
                        all_stores[store_name] = store_instance

            # 8. Apply Hydration — re-collect after server_load so loop-generated nodes are included
            for app in mounted_apps:
                child_bindings = list(app.get_child_bindings(recursive=True))
                child_components = [cb.childinstance for cb in child_bindings]
                fresh_all_components = [app] + child_components
                _apply_hydration_logic(app, fresh_all_components)

            # 9. Final render: serialize all stores into the initial state
            for store_name, store_instance in Store._registry.items():
                if store_name not in all_stores:
                    all_stores[store_name] = store_instance
            initial_state_json = _serialize_initial_state(all_stores, errors=error_collector)
        finally:
            set_error_sink(_prev_sink)
            if session_token is not None:
                from basis.shared.context import db_session_var
                db_session_var.reset(session_token)
            if session_generator is not None:
                try:
                    next(session_generator)
                except StopIteration:
                    pass

        return page_instance.render(request=request, initial_state_json=initial_state_json)
    finally:
        _set_render_pipeline(False)


def _render_page_csr(
    request: Request,
    page_cls=None,
    *,
    global_stores: list | None = None,
) -> str:
    """Client-side-rendered shell: the page shell plus the serialized initial
    state; the unified client entrypoint mounts the root component.

    Internal — use ``render_page`` / ``PageResponse.from_page``.
    ``global_stores`` is accepted for signature symmetry with the SSR engine.
    """
    from basis.shared.page import _set_render_pipeline

    _set_render_pipeline(True)
    try:
        page_instance = page_cls.load(request=request)
        page_instance.render_mode = "csr"
        return page_instance.render(request=request)
    finally:
        _set_render_pipeline(False)
