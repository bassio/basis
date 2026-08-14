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

def _serialize_initial_state(all_stores: dict[str, Store]) -> str:
    """Serialize the current state of all collected stores."""
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
        
    return json.dumps(initial_state, indent=2)

def _apply_hydration_logic(app, root_component_plus_child_components):
    """Apply hydration IDs and component IDs to the DOM tree."""
    def map_hydration_ids(root_element):
        stack = [(root_element, 0, [0])]
        stack_return = []
        while stack:
            obj, depth, path = stack.pop()
            path_str = "r:" + ":".join(map(str, path))
            stack_return.append((obj, depth, path_str))
            children = getattr(obj, 'children', [])
            valid_children = [c for c in children if type(c).__name__ != 'Comment']
            for i, child in reversed(list(enumerate(valid_children))):
                stack.append((child, depth + 1, path + [i]))
        return {hid: obj for obj, depth, hid in stack_return}

    hydration_ids_dict = map_hydration_ids(app.__element__)
    root_component_plus_child_nodes = [comp.__element__ for comp in root_component_plus_child_components]
    
    all_bindings_recursive = list(app.get_bindings(recursive=True))
    all_bindings_nodes_for_hydration = []
    for b in all_bindings_recursive:
        all_bindings_nodes_for_hydration.extend(b.marked_for_hydration())

    for hid, node in hydration_ids_dict.items():
        try:
            if any(node is target for target in all_bindings_nodes_for_hydration):
                node.setAttribute("data-hydration-id", hid)
            if any(node is target for target in root_component_plus_child_nodes):
                node.setAttribute("data-component-hydration-id", hid)
        except:
            pass

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
    initial_state_json = _serialize_initial_state(all_stores)
    return page_instance.render_full_page(request=request, initial_state_json=initial_state_json)
