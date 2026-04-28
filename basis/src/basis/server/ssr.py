"""
basis/server/ssr.py
-------------------
Server-Side Rendering helpers for Basis + FastAPI.

Usage example in a route:
    from basis.server.ssr import render_page
    from fastapi.responses import HTMLResponse

    @app.get("/")
    async def home(request: Request):
        from myapp.components.home import HomeComponent
        html = render_page(
            HomeComponent,
            title="My App",
            stores={"theme": theme_store},
            entry_module="/myapp/components/main.py",
        )
        return HTMLResponse(html)
"""

from __future__ import annotations

import json

from basis.server.tree_builder import html_to_element_tree
from basis.server.server_component import ServerComponent
from basis.shared.store import Store
from basis.shared.element import Element, DocumentType


def _serialize_store(store) -> dict:
    """
    Extract serialisable state from a Store instance.
    Skips private/dunder attributes and non-serialisable callables.
    """
    state = {}
    for k, v in store.__dict__.items():
        if k.startswith('_'):
            continue
        if callable(v):
            continue
        try:
            json.dumps(v)     # quick serialisability check
            state[k] = v
        except (TypeError, ValueError):
            pass
    return state


def render_page(
    component_cls,
    *,
    title: str = "Basis App",
    stores: dict | None = None,
    entry_module: str = "/main.py",
    pyscript_src: str = "/pyscript",
    pyscript_json_url: str = "/pyscript.json",
    extra_head: str = "",
    **kwargs,
) -> str:
    """
    Render a full HTML page with:

    - Fully server-resolved component HTML (via ServerComponent.render())
    - PyScript offline bootstrap
    - <script id="basis-initial-state"> JSON block for Store hydration
    - <py-config> pointing at pyscript.json

    Parameters
    ----------
    component_cls:
        A ServerComponent subclass to render.
    title:
        Page <title>.
    stores:
        Dict mapping store name → Store instance whose state should be embedded
        as the initial-state JSON block.  WebSocketStore on the client reads this
        automatically on startup.
    entry_module:
        URL path of the PyScript entry point (the .py file that calls mount_app
        or the new hydrate path).
    pyscript_src:
        URL for the offline PyScript core.js bundle.
    pyscript_json_url:
        URL for pyscript.json (the file-map used by PyScript to fetch Python modules).
    extra_head:
        Any additional raw HTML to inject inside <head>.
    **kwargs:
        Keyword arguments forwarded to ``component_cls.render(**kwargs)``.
    """
    # 1. Render the component tree to an HTML fragment
    #component_html = component_cls.render(**kwargs)
    #component_html = component_cls().__element__.__html__()
    
    # 2. Serialise store state
    initial_state: dict[str, dict] = {}
    if stores:
        for store_name, store_instance in stores.items():
            initial_state[store_name] = _serialize_store(store_instance)

    initial_state_json = json.dumps(initial_state, indent=2)

    # 3. Assemble the full page
    page_template = f"""
<html>
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{title}</title>

        <!-- PyScript offline bundle -->
        <link rel="stylesheet" href="{pyscript_src}/core.css" />
        <script type="module" src="{pyscript_src}/core.js" onload="window.pyscript = this.module;"></script>
        
        <script src="./basis/components/component.js"></script>

        <!-- Basis SSR: initial store state for client hydration -->
        <script id="basis-initial-state" type="application/json">
            {initial_state_json}
        </script>
        {extra_head}
    </head>
    <body>
        <div id="basis-ssr-root">
        </div>
        <!-- PyScript entry point: mounts/hydrates the application -->
        <script type="py" src="{entry_module}" config="{pyscript_json_url}"></script>
    </body>
</html>
"""
    
    page_tree = html_to_element_tree(page_template)

    page = page_tree['component']

    doctype = DocumentType(name="html")

    body = page.children[1]
    basis_ssr_root = body.children[0]

    app = component_cls.mount_app(basis_ssr_root)

    level = 0
    
    app.__element__._depth_level = level

    current_element = app.__element__

    def map_hydration_ids(root_element):
        """
        Traverses an Element tree and assigns deterministic IDs.
        Structure: 'r' (root) followed by indices: r:0, r:0:1, r:0:1:0, etc.
        """
        # Each entry: (element, path_as_tuple, index_at_current_level)
        # We start with the root at the first position (index 0) of the 'r' path.

        stack = [(root_element, 0, [0])]
        
        stack_return = []

        while stack:
                obj, depth, path = stack.pop()
                path_str = ":".join(map(str, path))
                path_str = "r:" + path_str
                stack_return.append((obj, depth, path_str))
                #print(f"Depth {depth} (Path: {path_str}): {obj}")
                

                children = getattr(obj, 'children', [])
                for i, child in reversed(list(enumerate(children))):
                    # Concatenate current path with the new index
                    stack.append((child, depth + 1, path + [i]))


        print("stack_return", stack_return)

        id_map = {}

        for obj, depth, path_str in iter(stack_return):
            id_map[path_str] = obj

        return id_map

    hydration_ids_dict = map_hydration_ids(app.__element__)

    child_bindings_recursive = [cb for cb  in app.get_child_bindings(recursive=True)]
    
    child_component_instances = [cb.childinstance for cb  in child_bindings_recursive]

    root_component_plus_child_components = [app, *child_component_instances]

    root_component_plus_child_nodes = [comp.__element__ for comp in root_component_plus_child_components]

    all_bindings_recursive = [cb for cb  in app.get_bindings(recursive=True)]
    
    all_bindings_nodes = [b.node for b in all_bindings_recursive]

    all_bindings_nodes_for_hydration = []
    
    for b in all_bindings_recursive:
        all_bindings_nodes_for_hydration.extend(b.marked_for_hydration())

    for hid, node in hydration_ids_dict.items():
        #print(hid, node)
        try:
            # Use identity check (is) instead of value equality (in) 
            # to avoid matching structurally identical but different elements.
            if any(node is target for target in all_bindings_nodes_for_hydration):
                node.setAttribute("data-hydration-id", hid)
            if any(node is target for target in root_component_plus_child_nodes):
                node.setAttribute("data-component-hydration-id", hid)
        except:
            pass

    page_html = doctype.__html__() + page.__html__()

    return page_html
