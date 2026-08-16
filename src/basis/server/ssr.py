"""
basis/server/ssr.py
-------------------
Server-Side Rendering helpers for Basis + FastAPI.
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

def _get_all_stores(
    page_cls,
    root_component_cls,
    stores: dict | None = None,
    global_stores: list | None = None
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

    return json.dumps(initial_state, indent=2)

def _apply_hydration_logic(app, root_component_plus_child_components):
    """Apply hydration IDs and component IDs to the DOM tree.

    Delegates to the shared set-based algorithm in ``shared/hydration.py``,
    which also stamps ``data-basis-text`` text ordinals.
    """
    apply_hydration_to_component(app, root_component_plus_child_components)

async def render_page_async(
    request: Request,
    root_component_cls,
    *,
    page_cls = None,
    title: str = "Basis App",
    stores: dict | None = None,
    global_stores: list | None = None,
    entry_module: str = "/basis/client/entrypoint_ssr.py",
    pyscript_src: str = "/pyscript",
    pyscript_json_url: str = "/pyscript.json",
    extra_head: str = "",
    **kwargs,
) -> str:

    if page_cls is None:
        from basis.shared.page import Page
        page_cls = Page

    from basis.shared.router import Route

    # Reset global registries to isolate per-request SSR state and avoid DetachedInstanceError
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    Route._route_registry.clear()

    # 1. Setup Page instance
    page_instance = page_cls.load(ssr=True, request=request)
    page_instance.title = title
    page_instance.entry_module = entry_module
    page_instance.pyscript_src = pyscript_src
    page_instance.pyscript_json_url = pyscript_json_url
    # 2. Collect stores
    all_stores = _get_all_stores(page_cls, root_component_cls, stores, global_stores)
    # 3. Mount App
    basis_ssr_root = None
    for node in page_instance.__element__.descendants:
        if hasattr(node, 'getAttribute') and node.getAttribute('id') == 'basis-ssr-root':
            basis_ssr_root = node
            break
            
    if not basis_ssr_root:
        basis_ssr_root = page_instance.__element__.children[1]

    # Phase 5 #4 — collect every binding-evaluation error raised during this
    # SSR render so it can be surfaced in the client overlay.  With the sink
    # installed, safe_eval returns an empty value instead of "[Error: ...]".
    error_collector = ErrorCollector()
    _prev_sink = get_error_sink()
    set_error_sink(error_collector)
    try:
        app = root_component_cls.mount_app(basis_ssr_root)

        # 4. Async Preload Phase
        child_bindings = list(app.get_child_bindings(recursive=True))
        child_components = [cb.childinstance for cb in child_bindings]
        all_components = [app] + child_components

        preload_tasks = []
        for comp in all_components:
            if hasattr(comp, 'server_load') and asyncio.iscoroutinefunction(comp.server_load):
                preload_tasks.append(comp.server_load())

        if preload_tasks:
            await asyncio.gather(*preload_tasks)

            # Re-check Store registry in case server_load created new stores
            for store_name, store_instance in Store._registry.items():
                if store_name not in all_stores:
                    all_stores[store_name] = store_instance

        # 5. Apply Hydration — re-collect after server_load so loop-generated nodes are included
        fresh_child_bindings = list(app.get_child_bindings(recursive=True))
        fresh_child_components = [cb.childinstance for cb in fresh_child_bindings]
        fresh_all_components = [app] + fresh_child_components
        _apply_hydration_logic(app, fresh_all_components)

        # 6. Final render
        for store_name, store_instance in Store._registry.items():
            if store_name not in all_stores:
                all_stores[store_name] = store_instance
        initial_state_json = _serialize_initial_state(all_stores, errors=error_collector)
    finally:
        set_error_sink(_prev_sink)
    return page_instance.render_full_page(request=request, initial_state_json=initial_state_json)
