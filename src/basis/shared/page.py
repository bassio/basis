import json
from basis.shared.component import Component
from basis.shared.element import Element, DocumentType
from basis.shared.store import Store


class Page(Component):
    doctype: DocumentType = DocumentType("html")
    title: str = "Basis App"
    entry_module: str = "/main.py"
    pyscript_src: str = "/pyscript"
    pyscript_json_url: str = "/pyscript.json"
    initial_state_json: str = "{}"
    root_component = None
    stores = []
    
    @classmethod
    def load(cls, ssr=False, request=None):
        if ssr:
            # Instantiate fresh versions of the page stores for this request if not already present.
            # Reconstruct from the persistent blueprint so the proper subclass (with its constructor
            # args) is used — `store.__class__(name)` would drop extra args (e.g. ModelStore's model).
            for store in getattr(cls, "stores", []):
                name = store.get_store_name()
                if name not in Store._registry:
                    store_instance = Store.reinstantiate(name) or Store(name)
                    if name == "router" and request and hasattr(request, "url"):
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
            for store in getattr(self.__class__, "stores", []):
                initial_state[store.get_store_name()] = store.serialize()
            if initial_state:
                initial_state_json = json.dumps(initial_state)

        self.initial_state_json = initial_state_json

        # 1. Collect modules to import on the client side
        entrypoint_imports = {}

        # Synthesized pages (built by @app.page / include_ssr_page) are server-side
        # shell config only — the client boots from the component file and cannot
        # import a class that was created at runtime, so don't emit it here.
        if not getattr(self.__class__, "__synthesized__", False):
            page_module_file = request.app.get_component_pyscript_vfs_path(self.__class__)

            if page_module_file and page_module_file != "basis.shared.page":
                entrypoint_imports[self.__class__.__name__] = page_module_file

        # 2. Locate <head> once; append client-configuration nodes.
        head_node = None
        for node in self.__element__.descendants:
            if hasattr(node, "tagName") and node.tagName.lower() == "head":
                head_node = node
                break

        if head_node:
            from basis.shared.element import Element, ElementString

            # 2a. Append the imports JSON configuration script in the <head>
            if entrypoint_imports:
                json_str = json.dumps(entrypoint_imports)
                imports_script = Element("script", {
                    "id": "basis-entrypoint-imports",
                    "type": "application/json"
                }, [ElementString(json_str)])

                head_node.appendChild(imports_script)

            # 2b. Dev-mode marker read by client tooling (e.g. the error
            # overlay).  Mirrors the HMR dev affordance: `basis dev --hmr`
            # sets BASIS_HMR=1 on the server.
            if getattr(request.app, "_start_hmr_watcher", False):
                head_node.appendChild(
                    Element("meta", {"name": "basis-mode", "content": "dev"}, [])
                )

        return self

    def render_full_page(self, request, initial_state_json=None):
        """
        Assembles the full HTML document with doctype.
        """
        self._prepare_full_page(request, initial_state_json)
        return self.doctype.__html__() + "\n" + self.__element__.outerHTML
