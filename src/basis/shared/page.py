import json
from basis.shared.component import Component
from basis.shared.element import Element, DocumentType
from basis.shared.store import Store, attach_app_to_store, FRAMEWORK_STORE_NAMES


def _page_store_names(stores) -> list[str]:
    """Normalize ``Page.stores`` to a list of store names.

    ``stores`` is a list of store *names* (strings); an empty list means "all
    auto-discovered stores". Store *instances* are intentionally not supported:
    declare a store at module scope (e.g. in a ``stores/`` module) and reference
    it by name, so the same module-scope-instance convention works on the
    server, the client, and for SSR/RPC blueprint reconstruction.
    """
    names = []
    for ref in stores:
        if isinstance(ref, str):
            names.append(ref)
            continue
        raise TypeError(
            f"Page.stores must be store names (strings), got a "
            f"{type(ref).__name__} instance. Instantiate the store at module "
            "scope (e.g. in a stores/ module) and reference it by name, "
            'e.g. stores = ["app_state"].'
        )
    return names


class Page(Component):
    doctype: DocumentType = DocumentType("html")
    title: str = "Basis App"
    entry_module: str = "/basis/client/entrypoint.py"
    pyscript_src: str = "/pyscript"
    pyscript_json_url: str = "/pyscript.json"
    initial_state_json: str = "{}"
    render_mode: str = "csr"
    root_component = None
    stores = []

    @classmethod
    def load(cls, ssr=False, request=None):
        if ssr:
            # Instantiate fresh versions of the page stores for this request if
            # not already present. ``stores`` is a list of store *names*; an
            # empty list means "all auto-discovered stores" (the persistent
            # blueprint registry).
            store_refs = getattr(cls, "stores", None) or Store.all_names()
            for name in _page_store_names(store_refs):
                if name not in Store._registry:
                    store_instance = Store.resolve(name)
                    if name == "router" and request and hasattr(request, "url"):
                        store_instance.current_path = request.url.path

        container = Element("html", {}, list())
        
        attributes = {"title": cls.title,
                      "entry_module": cls.entry_module,
                      "pyscript_src": cls.pyscript_src,
                      "pyscript_json_url": cls.pyscript_json_url,
                      "initial_state_json": cls.initial_state_json,
                      "render_mode": cls.render_mode}

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
        <meta name="basis-render-mode" content="{render_mode}" />
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

        # Page-level store names: the page's explicit store subset, or empty
        # (default-all). Framework control-plane stores always hydrate.
        declared_stores = getattr(self.__class__, "stores", None)
        page_store_names = _page_store_names(declared_stores) if declared_stores else []

        if initial_state_json is None:
            initial_state = {}
            names = set(page_store_names) or set(Store.all_names())
            # Framework control-plane stores ($plugins, $regions) must hydrate on
            # every page regardless of the page's store subset.
            names |= set(FRAMEWORK_STORE_NAMES)
            for name in names:
                instance = Store._registry.get(name) or Store.resolve(name)
                # App-bound stores (``_requires_app``, e.g. ``$plugins``) hold a
                # listing that requires the owning app. ``Store.resolve``
                # rebuilds a fresh instance with no ``_app``, so attach it +
                # recompute or the initial state serializes empty (the client
                # then hydrates a stale/empty view).
                attach_app_to_store(instance, request.app)
                initial_state[name] = instance.serialize()
            if initial_state:
                initial_state_json = json.dumps(initial_state)

        self.initial_state_json = initial_state_json

        # 1. Collect modules to import on the client side
        entrypoint_imports = {}

        # Synthesized pages (built by @app.page) are server-side shell config only
        # — the client boots from the component file and cannot import a class
        # that was created at runtime, so don't emit it here.
        if not getattr(self.__class__, "__synthesized__", False):
            # Server-side SSR path only: resolve the page class to its client VFS
            # import module via the app's live VFS registry (this branch never
            # runs under PyScript, so reaching into request.app is safe).
            page_module_file = request.app.vfs.component_module_name(self.__class__)

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

            # 2aa. Append the auto-discovered store module imports. The client
            # must import these modules so their module-scope store instances
            # exist and hydrate from #basis-initial-state.
            store_modules = getattr(request.app, "_discovered_store_modules", [])
            if store_modules:
                store_imports_script = Element("script", {
                    "id": "basis-store-imports",
                    "type": "application/json",
                }, [ElementString(json.dumps(store_modules))])
                head_node.appendChild(store_imports_script)

            # 2b. Page-level store names (the page's explicit store subset).
            # The client resolves these by name BEFORE importing components, so
            # every store exists before the view plane mounts. Default-all pages
            # emit nothing — their stores all come from #basis-store-imports and
            # the framework control-plane stores.
            if page_store_names:
                head_node.appendChild(Element("script", {
                    "id": "basis-page-stores",
                    "type": "application/json",
                }, [ElementString(json.dumps(page_store_names))]))

            # 2c. Dev-mode marker read by client tooling (e.g. the error
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


def _synthesize_page(
    component_cls,
    *,
    page_cls=None,
    title=None,
    stores=None,
    entry_module=None,
    pyscript_src=None,
):
    """Build a synthesized Page subclass that carries ``component_cls`` as its root.

    Used by ``@app.page`` to turn a root
    Component into a page without the developer writing a ``Page`` subclass. The
    synthesized class is server-side shell config only; it is marked
    ``__synthesized__`` so the client (which boots from the component file) never
    tries to import it via ``#basis-entrypoint-imports``.

    Because of that client boot path, page-level ``stores`` cannot reach the
    browser here — a shell that declares its own ``root_component`` or ``stores``
    is a complete page and belongs in ``app.include_page`` instead.
    """
    base = page_cls or Page

    if getattr(base, "root_component", None) is not None or getattr(base, "stores", None):
        raise ValueError(
            f"{base.__name__} already declares root_component/stores — it's a complete "
            f"page. Register it with app.include_page(path, page_cls={base.__name__}) "
            f"instead of decorating a component with it."
        )

    derived = type(
        f"{component_cls.__name__}Page",
        (base,),
        {
            "__module__": component_cls.__module__,
            "root_component": component_cls,
            "title": title if title is not None else getattr(base, "title", "Basis App"),
            "stores": list(stores) if stores is not None else list(getattr(base, "stores", [])),
            "__synthesized__": True,
        },
    )
    if entry_module is not None:
        derived.entry_module = entry_module
    if pyscript_src is not None:
        derived.pyscript_src = pyscript_src
    return derived
