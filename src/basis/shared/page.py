import json
import warnings

from basis.shared.component import Component
from basis.shared.element import Element, DocumentType
from basis.shared.store import Store, attach_app_to_store, FRAMEWORK_STORE_NAMES

#: True while the framework's render pipeline (``render_page`` /
#: ``PageResponse.from_page``) runs, so ``Page.load()`` / ``Page.render()`` do
#: not warn on their internal calls.
_render_pipeline_active = False


def _set_render_pipeline(active: bool) -> None:
    """Internal: mark whether we're inside the framework's render pipeline."""
    global _render_pipeline_active
    _render_pipeline_active = active


def page_aware_config_url(base_url: str, request) -> str:
    """Append ``?url=<route>`` to the framework's own ``pyscript.json`` config URL.

    The per-page manifest endpoint resolves the route to this page and injects
    its bootstrap under ``basis.bootstrap`` (see
    :func:`basis.server.bootstrap.page_bootstrap`). A fully custom
    ``pyscript_json_url`` (or one that already carries a query string) is
    returned unchanged.
    """
    url = getattr(request, "url", None)
    if (
        request is not None
        and url is not None
        and base_url
        and "?" not in base_url
        and base_url.rstrip("/").endswith("/pyscript.json")
    ):
        from urllib.parse import quote

        return f"{base_url}?url={quote(url.path)}"
    return base_url


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
    # Stylesheet URLs appended to the END of <body> — i.e. AFTER the SSR root
    # where the framework injects component <style> elements — so they land
    # later in the document and win the cascade at equal specificity (the
    # "your CSS comes later" rule). This is the framework-native home for a
    # user override stylesheet (e.g. a generated ``static/app.css``).
    stylesheets: tuple[str, ...] = ()

    @classmethod
    def load(cls, request=None):
        if not _render_pipeline_active:
            warnings.warn(
                "Page.load() is deprecated for direct use — serve pages via "
                "PageResponse.from_page() (or render_page()).",
                DeprecationWarning,
                stacklevel=2,
            )
        # Instantiate the page's stores — its explicit ``stores`` subset, or all
        # auto-discovered stores when empty — so they exist before the server
        # renders and serialize cleanly into the initial state. Runs for both SSR
        # and CSR (the server constructs the stores in either mode; only the old
        # code gated this to SSR). Registry-guarded and idempotent.
        store_refs = getattr(cls, "stores", None) or Store.all_names()
        for name in _page_store_names(store_refs):
            if name not in Store._registry:
                store_instance = Store.resolve(name)
                if name == "router" and request is not None and hasattr(request, "url"):
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

    def render(self, request, initial_state_json=None):
        """Assemble the full HTML document (shell + initial state + head/body).

        This is the single server-side page-render funnel — both the SSR and CSR
        engines end in this method. It is internal: serve pages via
        ``PageResponse.from_page()`` / ``render_page()``. Calling it (or
        ``Page.load()``) directly is the legacy pattern and is deprecated.
        """
        if not _render_pipeline_active:
            warnings.warn(
                "Page.render() (and Page.load()) are deprecated for direct use — "
                "serve pages via PageResponse.from_page() (or render_page()).",
                DeprecationWarning,
                stacklevel=2,
            )

        # Page-aware PyScript config: the per-page manifest is served at
        # ?url=<route> (the endpoint injects this page's bootstrap under
        # basis.bootstrap). Computed here because render() always has the request
        # — covering SSR, CSR, and hand-rolled routes that call Page.load()
        # without one. The assignment re-renders the config attribute (verified)
        # and page_aware_config_url is idempotent.
        self.pyscript_json_url = page_aware_config_url(self.pyscript_json_url, request)

        # Self-register the route → page mapping so /pyscript.json?url=<route>
        # resolves this page even when it was served via a hand-rolled route
        # (e.g. a bare @app.get("/") that renders the shell directly). Real HTTP
        # requests always carry .url; fake/test requests may not.
        url = getattr(request, "url", None)
        pages = getattr(request.app, "_pages", None)
        if pages is not None and url is not None:
            pages.setdefault(url.path, self.__class__)

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
                # Request-pref hook: a store may opt in by defining
                # ``apply_request(request)`` (e.g. ``$theme`` reads its
                # ``basis_theme`` cookie) so the CSR initial state is themed.
                apply_request = getattr(instance, "apply_request", None)
                if callable(apply_request):
                    try:
                        apply_request(request)
                    except Exception:
                        pass
                initial_state[name] = instance.serialize()
            if initial_state:
                initial_state_json = json.dumps(initial_state)

        self.initial_state_json = initial_state_json

        # 2. Locate <head> once; append client-configuration nodes. The client
        # pre-mount plan (stores/headless/entrypoint/page stores) no longer lives
        # in the DOM — it is served per-page via /pyscript.json?url=<route> under
        # ``basis.bootstrap`` and read from ``pyscript.config`` (see
        # basis/server/bootstrap.py::page_bootstrap + client/entrypoint.py).
        head_node = None
        for node in self.__element__.descendants:
            if hasattr(node, "tagName") and node.tagName.lower() == "head":
                head_node = node
                break

        if head_node:
            from basis.shared.element import Element

            # 2c. Dev-mode marker read by client tooling (e.g. the error
            # overlay).  Mirrors the HMR dev affordance: `basis dev --hmr`
            # sets BASIS_HMR=1 on the server.
            if getattr(request.app, "_start_hmr_watcher", False):
                head_node.appendChild(
                    Element("meta", {"name": "basis-mode", "content": "dev"}, [])
                )

        # 3. Declared stylesheets go at the END of <body> (after the SSR root),
        # so they load after the framework's component <style> elements and win
        # at equal specificity. Served for both SSR and CSR (this shell is
        # emitted in either mode).
        stylesheets = getattr(self.__class__, "stylesheets", ()) or ()
        if stylesheets:
            body_node = None
            for node in self.__element__.descendants:
                if hasattr(node, "tagName") and node.tagName.lower() == "body":
                    body_node = node
                    break
            if body_node is not None:
                for href in stylesheets:
                    body_node.appendChild(
                        Element("link", {"rel": "stylesheet", "href": href}, [])
                    )

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
    ``__synthesized__`` so the per-page manifest never emits it as the client
    ``entrypoint`` (the client boots from the component file instead).

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
