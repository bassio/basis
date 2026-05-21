"""
basis/server/ssr.py
-------------------
Server-Side Rendering helpers for Basis + FastAPI.
"""

from __future__ import annotations
from asyncio import exceptions
import asyncio
import json

from fastapi import Request

from basis.server.tree_builder import html_to_element_tree
from basis.shared.store import Store
from basis.shared.element import Element, DocumentType

def _get_all_stores(
    page_cls,
    root_component_cls,
    stores: dict | None = None,
    global_stores: list | None = None
) -> dict[str, Store]:
    """Collect all stores from Page, Component, and global configurations."""
    all_stores = stores or {}
    for cls in [page_cls, root_component_cls]:
        if hasattr(cls, '__basis_stores__'):
            for cfg in cls.__basis_stores__:
                name = cfg['name']
                if name not in all_stores:
                    if name not in Store._registry:
                        Store(name)
                    all_stores[name] = Store._registry[name]

    if global_stores:
        for cfg in global_stores:
            name = cfg['name']
            if name not in all_stores:
                if name not in Store._registry:
                    Store(name)
                all_stores[name] = Store._registry[name]
    return all_stores

def _serialize_initial_state(all_stores: dict[str, Store]) -> str:
    """Serialize the current state of all collected stores."""
    initial_state: dict[str, dict] = {}
    for store_name, store_instance in all_stores.items():
        initial_state[store_name] = store_instance.serialize()
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
    entry_module: str = "/basis/components/entrypoint_ssr.py",
    pyscript_src: str = "/pyscript",
    pyscript_json_url: str = "/pyscript.json",
    extra_head: str = "",
    **kwargs,
) -> str:

    if page_cls is None:
        from basis.shared.page import Page
        page_cls = Page
    
    # 1. Collect stores
    all_stores = _get_all_stores(page_cls, root_component_cls, stores, global_stores)

    # 2. Setup Page instance
    page_instance = page_cls.load()
    page_instance.title = title
    page_instance.entry_module = entry_module
    page_instance.pyscript_src = pyscript_src
    page_instance.pyscript_json_url = pyscript_json_url
    
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
    initial_state_json = _serialize_initial_state(all_stores)
    return page_instance.render_full_page(request=request, initial_state_json=initial_state_json)


async def render_page_async_slots(
    request: Request,
    root_component_or_slots,
    *,
    page_cls = None,
    title: str = "Basis App",
    stores: dict | None = None,
    global_stores: list | None = None,
    entry_module: str = "/basis/components/entrypoint_ssr.py",
    pyscript_src: str = "/pyscript",
    pyscript_json_url: str = "/pyscript.json",
    extra_head: str = "",
    **kwargs,
) -> str:
    """
    Async version of render_page_slots supporting slot composition and auto-discovery hydration.
    """
    if page_cls is None:
        from basis.shared.page import Page
        page_cls = Page

    # 1. Standardize inputs to slots dictionary
    if isinstance(root_component_or_slots, dict):
        slots_config = root_component_or_slots
    else:
        slots_config = {None: root_component_or_slots}

    # 2. Collect all stores
    all_stores = {}
    for comp_cls in slots_config.values():
        if comp_cls:
            all_stores.update(_get_all_stores(page_cls, comp_cls, stores, global_stores))

    # 3. Mount each component detached and assign slot attributes
    light_children = []
    mounted_apps = []
    
    for slot_name, comp_cls in slots_config.items():
        if not comp_cls:
            continue
            
        # Create a detached container div
        wrapper = Element("div", {}, [])
        app = comp_cls.mount_app(wrapper, replace=False)
        
        # Set slot attribute directly on the component root element
        if slot_name:
            app.__element__.setAttribute("slot", slot_name)
            
        light_children.append(app.__element__)
        mounted_apps.append(app)

    # 5. Async Preload Phase (server_load lifecycle for all islands)
    all_components = []
    for app in mounted_apps:
        child_bindings = list(app.get_child_bindings(recursive=True))
        child_components = [cb.childinstance for cb in child_bindings]
        all_components.extend([app] + child_components)

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

    # 6. Load Page and compose layout via fill_slots
    page_instance = page_cls.load()
    page_instance.title = title
    page_instance.entry_module = entry_module
    page_instance.pyscript_src = pyscript_src
    page_instance.pyscript_json_url = pyscript_json_url

    # 7. Apply Hydration independently for each island
    for app in mounted_apps:
        child_bindings = list(app.get_child_bindings(recursive=True))
        child_components = [cb.childinstance for cb in child_bindings]
        island_components = [app] + child_components
        _apply_hydration_logic(app, island_components)

    # 8. Final render with initial state JSON
    initial_state_json = _serialize_initial_state(all_stores)
    return page_instance.render_full_page(request=request, initial_state_json=initial_state_json)
