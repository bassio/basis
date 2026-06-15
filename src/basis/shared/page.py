import asyncio
import json
from basis.shared.component import Component
from basis.shared.element import Element, DocumentType
from basis.shared.store import Store


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


class Page(Component):
    doctype: DocumentType = DocumentType("html")
    title: str = "Basis App"
    entry_module: str = "/main.py"
    pyscript_src: str = "/pyscript"
    pyscript_json_url: str = "/pyscript.json"
    initial_state_json: str = "{}"
    entrypoint_components = []
    entrypoint_stores = []
    
    @classmethod
    def load(cls, ssr=False, request=None):
        if ssr:
            # Instantiate fresh versions of the entrypoint stores for this request if not already present
            for store in getattr(cls, "entrypoint_stores", []):
                if store.get_store_name() not in Store._registry:
                    store_instance = store.__class__(store.get_store_name())
                    if store.get_store_name() == "router" and request and hasattr(request, "url"):
                        store_instance.current_path = request.url.path

        container = Element("html", {}, list())
        
        attributes = {"title": cls.title,
                      "entry_module": cls.entry_module,
                      "pyscript_src": cls.pyscript_src,
                      "pyscript_json_url": cls.pyscript_json_url,
                      "initial_state_json": cls.initial_state_json}

        page_instance = cls.mount(container, replace=False, **attributes)
        page_instance.__element__ = container.children[0]
        
        return page_instance

    def head(self):
        """Override to add custom head content."""
        return ""

    def body(self):
        """Override to add main page content."""
        return ""

    def template(self):
        """
<html>
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{title}</title>

        <!-- PyScript offline bundle -->
        <link rel="stylesheet" href="{pyscript_src}/core.css" />
        <script type="module" src="{pyscript_src}/core.js" onload="window.pyscript = this.module;"></script>
        
        <script src="./basis/client/component.js"></script>

        <!-- PyScript entry point: mounts/hydrates the application -->
        <script type="py" src="{entry_module}" config="{pyscript_json_url}"></script>

        <!-- Basis SSR: initial store state for client hydration -->
        <script id="basis-initial-state" type="application/json">
            {initial_state_json}
        </script>
        
    </head>
    <body>
        <div id="basis-ssr-root"></div>
    </body>
</html>
"""

    def _prepare_full_page(self, request, initial_state_json=None):

        if initial_state_json is None:
            initial_state = {}
            for store in getattr(self.__class__, "entrypoint_stores", []):
                initial_state[store.get_store_name()] = store.serialize()
            if initial_state:
                initial_state_json = json.dumps(initial_state)

        self.initial_state_json = initial_state_json

        # 1. Collect modules to import on the client side
        entrypoint_imports = {}
        
        page_module_file = request.app.get_component_pyscript_vfs_path(self.__class__)

        if page_module_file and page_module_file != "basis.shared.page":
            entrypoint_imports[self.__class__.__name__] = page_module_file

        # 2. Append the imports JSON configuration script in the <head>
        if entrypoint_imports:
            head_node = None
            for node in self.__element__.descendants:
                if hasattr(node, "tagName") and node.tagName.lower() == "head":
                    head_node = node
                    break

            if head_node:
                from basis.shared.element import Element, ElementString

                json_str = json.dumps(entrypoint_imports)
                imports_script = Element("script", {
                    "id": "basis-entrypoint-imports",
                    "type": "application/json"
                }, [ElementString(json_str)])

                head_node.appendChild(imports_script)

        return self

    def render_full_page(self, request, initial_state_json=None):
        """
        Assembles the full HTML document with doctype.
        """
        self._prepare_full_page(request, initial_state_json)
        return self.doctype.__html__() + "\n" + self.__element__.outerHTML

    async def render_full_page_ssr(self, request, initial_state_json=None):
        from basis.shared.store import Store

        # Ensure the router's current path is up-to-date for this request
        router_store = Store._registry.get("router")
        if router_store and hasattr(request, "url"):
            router_store.current_path = request.url.path

        self._prepare_full_page(request, initial_state_json)

        mounted_apps = []

        basis_ssr_root = None
        for node in self.__element__.descendants:
            if hasattr(node, 'getAttribute') and node.getAttribute('id') == 'basis-ssr-root':
                basis_ssr_root = node
                break
                
        if not basis_ssr_root:
            raise Exception("Could not find <div id='basis-ssr-root'> in page shell template")
            basis_ssr_root = self.__element__.children[1]

        for comp_cls in self.entrypoint_components:
            app = comp_cls.mount_app(basis_ssr_root, replace=False)
            mounted_apps.append(app)

        session_token = None
        session_generator = None
        db_session = None

        if hasattr(request, "app") and hasattr(request.app, "get_session") and request.app.get_session is not None:
            import inspect
            from basis.shared.context import db_session_var
            get_session_func = request.app.get_session
            
            if inspect.isgeneratorfunction(get_session_func):
                session_generator = get_session_func()
                try:
                    db_session = next(session_generator)
                except StopIteration:
                    pass
            else:
                db_session = get_session_func()
                
            if db_session is not None:
                session_token = db_session_var.set(db_session)

        try:
            # Collect components for server_load (pre-data collection)
            all_components = []
            for app in mounted_apps:
                child_bindings = list(app.get_child_bindings(recursive=True))
                child_components = [cb.childinstance for cb in child_bindings]
                all_components.extend([app] + child_components)
                if hasattr(app, '_mounted_providers'):
                    for provider in app._mounted_providers:
                        if provider not in all_components:
                            all_components.append(provider)

            # Run server_load FIRST so stores get populated and reactive loops create nodes
            preload_tasks = []
            for comp in all_components:
                if hasattr(comp, 'server_load') and asyncio.iscoroutinefunction(comp.server_load):
                    preload_tasks.append(comp.server_load())
                    
            if preload_tasks:
                await asyncio.gather(*preload_tasks)

            # Apply Hydration AFTER server_load — the tree now contains loop-generated nodes
            for app in mounted_apps:
                child_bindings = list(app.get_child_bindings(recursive=True))
                child_components = [cb.childinstance for cb in child_bindings]
                island_components = [app] + child_components
                _apply_hydration_logic(app, island_components)

            # Serialize ALL stores (including ones created by StoreProvider) into initial state
            initial_state = {}
            for store_name, store_instance in Store._registry.items():
                initial_state[store_name] = store_instance.serialize()

            if initial_state:
                initial_state_json = json.dumps(initial_state)
            else:
                initial_state_json = json.dumps({})

            self.initial_state_json = initial_state_json
            
            # Final render with initial state JSON
            return self.doctype.__html__() + "\n" + self.__element__.outerHTML

        finally:
            if session_token is not None:
                from basis.shared.context import db_session_var
                db_session_var.reset(session_token)
            if session_generator is not None:
                try:
                    next(session_generator)
                except StopIteration:
                    pass
