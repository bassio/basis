import json

from basis.shared.component import Component, IS_CLIENT
from basis.shared.element import Element, DocumentType
from basis.shared.store import Store, attach_app_to_store, FRAMEWORK_STORE_NAMES
from basis.shared.serialization import json_dumps_script_safe

#: A Page's client blueprint must come from a structure-preserving document
#: parser: ``<template>.innerHTML`` drops the ``<html>/<head>/<body>`` wrappers,
#: and an ``XMLSerializer`` round-trip double-encodes raw-text entities
#: (``<script>``/``<style>``). See
#: ``client/component.py::_build_html_document_blueprint``.



#: Framework mobile viewport base CSS.
#:
#: Document-level rules only: component styles live in shadow roots and can never
#: reach ``html``/``body``, so the page-level mobile rules ship as a light-DOM
#: ``<style id="basis-viewport">`` in ``<head>``. Neutral and theme-agnostic —
#: safe for the fixed-viewport workbench and the document-flow site paradigm.
#:
#: The block reaches the template as DATA through the ``text-content`` attribute
#: binding (see the ``viewport_base_css`` class attribute), never as inline
#: template text: ``{``/``}`` inside a raw-text element would be parsed as
#: ``{expr}`` fields.
_VIEWPORT_BASE_CSS = """\
/* basis mobile viewport base */
html {
    /* iOS: prevent auto font-inflation on rotate/zoom; ``100%`` (not ``none``)
       still lets the user zoom manually. */
    -webkit-text-size-adjust: 100%;
    text-size-adjust: 100%;
}
button, a, input, select, textarea, [role="button"] {
    /* no double-tap zoom, no 300ms tap delay on interactive controls */
    touch-action: manipulation;
}
"""

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


def _served_head_component_style_names():
    """Client-only: the ``data-component-class`` names of the served page head's
    component-style LOOP items, or ``None`` when unavailable (server).

    The served ``<head>`` is the source of truth for page chrome: the server
    renders it, so whatever it lists is the canonical component-style set for
    THIS page. Reading it back lets the client render exactly that set instead
    of re-deriving from its own process-global component registry.

    Only styles that carry ``data-item-key`` count — those are the keyed-loop
    items the server rendered. Standalone chrome a component self-injects at
    boot (e.g. the dev ``ErrorOverlay``'s own ``<style data-component-class>``,
    appended to ``<head>`` by ``mount_error_overlay``) has NO ``data-item-key``:
    it is deliberately not part of the loop, so it must not make the client
    believe the server loop shipped that component.
    """
    try:
        from pyscript import document
    except Exception:
        return None
    try:
        names = set()
        for el in document.head.querySelectorAll(
            "style[data-component-class][data-item-key]"
        ):
            n = el.getAttribute("data-component-class")
            if n:
                names.add(str(n))
        return names
    except Exception:
        return None


def _filter_style_sources(sources, served_names):
    """Keep only the ordered style sources whose component name appears in
    ``served_names`` (the served head's set); no filtering when ``None``."""
    if served_names is None:
        return list(sources)
    return [s for s in sources if s[1] in served_names]


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


def _hyphen_tag(name: str) -> str:
    """Kebab-case a class name into a hyphenated host tag (``HelloBasis`` →
    ``hello-basis``, ``AppContainer`` → ``app-container``).

    Used by :meth:`Page._declarative_root_tag` to derive a deterministic host
    tag for a root component that does not declare a hyphenated ``__tag__``.
    Server and client derive it from the same class name, so hydration paths
    match.
    """
    import re

    s1 = re.sub(r"(.)([A-Z][a-z]+)", r"\1-\2", name)
    s2 = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s1)
    return s2.replace("_", "-").lower()


def _replace_comment_anchors(html_root, anchor_data, elements):
    """Replace every ``<!-- anchor_data -->`` comment node under the server tree
    ``html_root`` with ``elements`` (each a detached ``Element``).

    Comment anchors pin where assembly-time chrome belongs in the Page template
    — the user stylesheet ``<link>``s at the very END of ``<body>``. Comments
    never count toward hydration numbering, so replacing them before the
    stamping pass can never shift an ``h:``/``b:`` path.

    When ``elements`` is empty the anchor comment is removed too, so prod
    output carries no stray marker. Returns whether any anchor was found.
    """
    # Collect first — mutating the tree while iterating descendants is unsafe.
    targets = []
    for node in html_root.descendants:
        if type(node).__name__ == "Comment" and node.data == anchor_data:
            targets.append(node)
    for comment in targets:
        parent = comment.parentNode
        if elements:
            for el in elements:
                parent.insertBefore(el, comment)
        if parent is not None:
            try:
                parent.children.remove(comment)
            except ValueError:
                pass
        comment.parent = None
    return bool(targets)


class Page(Component):
    doctype: DocumentType = DocumentType("html")
    title: str = "Basis App"
    entry_module: str = "/basis/client/entrypoint.py"
    pyscript_src: str = "/pyscript"
    pyscript_json_url: str = "/pyscript.json"
    initial_state_json: str = "{}"
    render_mode: str = "ssr"
    # Mobile viewport policy. The default is the
    # mobile-correct layout viewport: ``viewport-fit=cover`` opts into
    # ``env(safe-area-inset-*)`` on notched devices, and
    # ``interactive-widget=resizes-content`` makes the on-screen keyboard resize
    # the layout instead of covering it. Override on a ``Page`` subclass to opt
    # out (e.g. ``interactive-widget=resizes-visual`` for a full-screen reader).
    viewport: str = (
        "width=device-width, initial-scale=1.0, viewport-fit=cover, "
        "interactive-widget=resizes-content"
    )
    #: The framework mobile viewport base CSS rendered into
    #: ``<style id="basis-viewport">`` in the base template's ``<head>``. A data
    #: field so it can be overridden per-page; defaults to ``_VIEWPORT_BASE_CSS``.
    viewport_base_css: str = _VIEWPORT_BASE_CSS
    #: Dev-mode marker — ``True`` only when the HMR dev watcher runs. Bound into
    #: the always-present in-tree ``<meta name="basis-dev-mode"
    #: content="{basis_dev_mode}">`` head meta as an ATTRIBUTE binding (the
    #: ``content`` value carries the mode, ``True``/``False``), so no
    #: ``if``-binding anchor is needed in ``<head>``.
    basis_dev_mode: bool = False
    #: iOS standalone meta: the three ``apple-mobile-web-app-*`` tags are
    #: emitted into the ``<head>`` when on.
    #: Default-on is harmless (they are inert until the page is added to the
    #: home screen, and they are what make an installed app fullscreen with a
    #: sane status bar); set ``False`` to omit all three.
    apple_web_app: bool = True
    #: ``apple-mobile-web-app-status-bar-style``. ``black-translucent`` (status
    #: bar overlays the app edge-to-edge) rides on the D6 safe-area guard the
    #: framework shell ships (title/status-bar ``env()`` padding); a
    #: document-flow site that does not pad its top edge should set this to
    #: ``"default"`` (opaque status bar) instead.
    apple_status_bar_style: str = "black-translucent"
    root_component = None
    stores = []
    #: User stylesheet URLs, assembled last in ``<body>`` — after the app and the
    #: ``<head>`` component styles — so they load later and win the cascade at
    #: equal specificity (the "your CSS comes later" rule). The base template
    #: carries a ``<!-- basis:user-stylesheets -->`` anchor there and
    #: :meth:`Page._render` replaces it with these ``<link rel="stylesheet">``.
    #: This is the framework-native home for a user override stylesheet (e.g. a
    #: generated ``static/app.css``); a ``<link>`` loop would be cleaner but
    #: races the app at the same trailing body slot.
    stylesheets: tuple[str, ...] = ()

    def component_style_items(self):
        """Ordered component style items for the in-tree ``<head>``
        component-style loop.

        Each item is a dict the loop template reads: ``uid`` (stable
        reconciliation key), ``name`` (component class), ``extra`` (``''`` for
        the main stylesheet, else the ``@extra_style`` name) and ``css`` (the
        formatted stylesheet). The set and order come from
        ``BaseComponent._ordered_style_sources``.

        Server vs client parity is guaranteed by making the SERVED page head
        authoritative, not by enumerating a shared registry: the server renders
        the full ordered set (the shell it ships defines the page's chrome), and
        on the client this method returns only the sources whose component is
        present in the served ``<head>``'s ``<style data-component-class>`` set.
        So a client registry that also holds dormant client-only components
        (e.g. the dev ``ErrorOverlay``, which the server never imports and which
        self-injects its stylesheet when it mounts) can never introduce a head
        item the server did not ship — no spurious "loop item not found"
        mismatch, and no namespace heuristics.
        """
        sources = _filter_style_sources(
            self.__class__._ordered_style_sources(),
            _served_head_component_style_names(),
        )
        return [
            {
                "uid": f"{name}||{extra or 'main'}",
                "name": name,
                "extra": extra or "",
                "css": css,
            }
            for (_cls, name, extra, css) in sources
        ]

    def apple_meta_items(self):
        """Ordered iOS standalone meta items for the base template's keyed head
        loop.

        One ``{key, name, content}`` dict per ``apple-mobile-web-app-*`` tag;
        ``[]`` when ``Page.apple_web_app`` is False (the loop renders nothing —
        byte-stable). Rendered as a head loop (NOT an ``if``-binding: an if-node
        wraps in a ``<div style="display: contents">`` anchor, which is illegal
        inside ``<head>``). The tags are inert until the page is added to the
        home screen. ``black-translucent`` (default) rides on the D6 safe-area
        guard the shell ships; a document-flow page that doesn't pad its top
        edge should set ``apple_status_bar_style = \"default\"``.
        """
        if not getattr(self, "apple_web_app", True):
            return []
        return [
            {
                "key": "name:apple-mobile-web-app-capable",
                "name": "apple-mobile-web-app-capable",
                "content": "yes",
            },
            {
                "key": "name:apple-mobile-web-app-title",
                "name": "apple-mobile-web-app-title",
                "content": str(getattr(self, "title", "Basis App")),
            },
            {
                "key": "name:apple-mobile-web-app-status-bar-style",
                "name": "apple-mobile-web-app-status-bar-style",
                "content": str(
                    getattr(self, "apple_status_bar_style", "black-translucent")
                ),
            },
        ]

    @classmethod
    def _load(cls, request=None):
        """Mount this Page class into a fresh ``<html>`` shell and return the
        instance. Internal — the SSR/CSR engines call it; the blessed serving
        API is ``PageResponse.from_page`` / ``render_page``."""
        # Instantiate the page's stores — its explicit ``stores`` subset, or all
        # auto-discovered stores when empty — so they exist before the server
        # renders and serialize cleanly into the initial state. Registry-guarded
        # and idempotent.
        store_refs = getattr(cls, "stores", None) or Store.all_names()
        for name in _page_store_names(store_refs):
            if name not in Store._registry:
                store_instance = Store.resolve(name)
                if name == "router" and request is not None and hasattr(request, "url"):
                    store_instance.current_path = request.url.path
        # Framework control-plane stores ($meta / $device / $network) are
        # guaranteed to exist at mount, like the plugin registry. $meta's head
        # `<meta for>` loop always binds it (empty items render nothing);
        # $device / $network carry neutral defaults that client probes overwrite
        # after mount. FRAMEWORK_STORE_NAMES also serializes them on strict
        # ``Page.stores`` pages.
        from basis.shared.meta import ensure_meta_store
        from basis.shared.device import ensure_device_store
        from basis.shared.network import ensure_network_store

        ensure_meta_store()
        ensure_device_store()
        ensure_network_store()
        container = Element("html", {}, list())
        
        attributes = {"title": cls.title,
                      "entry_module": cls.entry_module,
                      "pyscript_src": cls.pyscript_src,
                      "pyscript_json_url": cls.pyscript_json_url,
                      "initial_state_json": cls.initial_state_json,
                      "render_mode": cls.render_mode,
                      "viewport": cls.viewport,
                      # Dev-mode marker: bound at MOUNT time (True only when the
                      # HMR dev watcher runs); the head meta's
                      # content="{basis_dev_mode}" attribute binding reads it.
                      "basis_dev_mode": bool(
                          request is not None
                          and getattr(getattr(request, "app", None),
                                      "_start_hmr_watcher", False)
                      )}

        page_instance = cls.mount(container, replace=False, **attributes)
        page_instance.__element__ = container.children[0]
        
        return page_instance

    @classmethod
    def _declarative_root_tag(cls):
        """The hyphenated host ``__tag__`` this Page mounts its root app under,
        or ``None`` when the Page has no root (static page).

        The Page owns its root as a nested ``ChildBinding`` under a hyphenated
        host tag in its ``<body>`` app slot — the root is just another
        component. A root that declares a hyphenated ``__tag__`` mounts under it
        (e.g. jotter ``AppContainer.__tag__ = "app-container"``); one that does
        not gets a kebab-case tag derived from its class name, so every boot
        path mounts declaratively through :meth:`Page.mount_root_app`.
        """
        root_component = getattr(cls, "root_component", None)
        if root_component is None:
            return None
        tag = getattr(root_component, "__tag__", None)
        if isinstance(tag, str) and "-" in tag:
            return tag.lower()
        # No declared hyphen tag → derive one deterministically so the root can
        # still be mounted as a declarative child (both server and client derive
        # it from the same class name, so hydration paths match).
        return _hyphen_tag(root_component.__name__)

    def mount_root_app(self):
        """Declaratively mount this Page's root component into its ``<body>``
        app slot as a real nested child.

        Replaces the inert ``<!-- basis:app-root -->`` slot marker with a live
        ``<{root_tag}>`` element and mounts the root component into it via a
        ``ChildBinding`` (the same light-DOM nested-component path every
        template child uses), so the app is ONE owned node of the Page's tree,
        ordered deterministically before the trailing user-stylesheet ``<link>``s
        with no imperative relocation. ``@include_store``/``@include_model``
        providers mount ahead of it exactly as :meth:`BaseComponent.mount_with_providers`
        mounts them.

        A derived host is given ``display: contents`` so a root that did not opt
        into the declarative contract keeps its original layout — the host adds
        no box. A root that DECLARES its tag styles its own host (the
        ``ui-theme-provider { display: contents }`` pattern, e.g. jotter
        ``AppContainer``).

        Caller decides *when* (the engines: SSR mounts the app, CSR shells do
        not) — this method never mounts into the live document by itself; it
        acts on ``self.__element__`` (the server tree or the staged client
        tree). Returns the mounted root instance, or ``None`` when the Page has
        no root (static page).
        """
        root_component = self.__class__.root_component
        if root_component is None:
            return None
        declared = getattr(root_component, "__tag__", None)
        derived = not (isinstance(declared, str) and "-" in declared)
        tag = self.__class__._declarative_root_tag()

        from basis.shared.base_component import (
            _container_last_child,
            _find_anchor_comment,
            _mount_root_providers,
            _move_after,
        )

        html_root = self.__element__
        body = None
        for child in getattr(html_root, "children", ()):
            if getattr(child, "nodeName", "").lower() == "body":
                body = child
                break
        if body is None:
            return None

        # Providers first (appended), then the root host, then relocate the
        # whole block to the app-root slot and drop the marker comment, so the
        # app stays one deterministic node ordered before the trailing links.
        ref = _container_last_child(body)
        anchor = _find_anchor_comment(body, "basis:app-root")
        providers = _mount_root_providers(root_component, body)
        host = self.__class__._create_element(tag)
        if derived:
            # A derived host must not add a box: the root did not declare a tag
            # (so it has no `{tag} { display: contents }` stylesheet of its
            # own). Deterministic on both server and client, so it never shifts
            # a hydration path.
            try:
                host.setAttribute("style", "display: contents")
            except Exception:
                pass
        body.appendChild(host)

        from basis.shared.bindings import ChildBinding

        binding = ChildBinding(
            component_instance=self, node=host, childclass=root_component
        )
        self.add_binding(binding)
        app = binding.childinstance
        app._mounted_providers = providers

        if anchor is not None and ref is not None:
            _move_after(body, ref, anchor)
            try:
                getattr(anchor, "remove", lambda: None)()
            except Exception:
                pass
        return app

    def template(self):
        """
<html>
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="{viewport}" />
        <meta name="basis-render-mode" content="{render_mode}" />
        <meta name="basis-dev-mode" content="{basis_dev_mode}" />

        <title>{title}</title>

        <!-- PyScript bundle -->
        <link rel="stylesheet" href="{pyscript_src}/core.css" />
        <script type="module" src="{pyscript_src}/core.js" onload="window.pyscript = this.module;"></script>
        
        <script src="/basis/client/component.js"></script>

        <!-- PyScript entry point: mounts/hydrates the application -->
        <script type="py" src="{entry_module}" config="{pyscript_json_url}"></script>

        <!-- Initial store state -->
        <script id="basis-initial-state" type="application/json">
            {initial_state_json}
        </script>

        <style id="basis-viewport" text-content="{viewport_base_css}"></style>

        <!-- component styles -->
        <style text-content="{item['css']}" for="item" in="{component_style_items()}" key="uid" data-component-class="{item['name']}" data-extra-style="{item['extra']}"></style>

        <!-- document meta ($meta) -->
        <meta for="m" in="{$meta.items}" key="key" name="{m['name']}" content="{m['content']}" />

        <!-- iOS standalone meta -->
        <meta for="m" in="{apple_meta_items()}" key="key" name="{m['name']}" content="{m['content']}" />
    </head>
    <body>
        <!-- basis:app-root -->
        <!-- basis:user-stylesheets -->
    </body>
</html>
"""

    @classmethod
    def _initialize_blueprint(cls):
        """Client/server Page blueprint build.

        The server parses a Page template with its own HTML parser, which keeps
        the ``<html>/<head>/<body>`` document elements — so the server uses the
        generic path unchanged. A browser ``<template>.innerHTML`` parse, by
        contrast, runs in *fragment* mode and DROPS the document-level wrappers,
        flattening the head/body children into one list — which would destroy
        the two-region structure whole-page hydration needs. On the client the
        Page therefore parses its template with a structure-preserving document
        parser (``DOMParser``) and keeps the resulting ``<html>`` as the
        blueprint (see ``basis.client.component._build_html_document_blueprint``).
        """
        if not IS_CLIENT:
            super()._initialize_blueprint()
            return
        from basis.client.component import _build_html_document_blueprint

        setattr(cls, "__blueprint__", _build_html_document_blueprint(cls))

    # ── Whole-page client mount (HYDRATION-WHOLEPAGE.md No.2 / Option A) ──────
    # The client mounts the PAGE (not just the root component) so the Page's own
    # <head> bindings are kept alive by real hydration instead of being
    # server-frozen. CSR adopts the served shell (head h: + body b: chrome) and
    # client-renders the app into <body>; SSR hydrates the whole served document
    # in place (head h: + body b: incl. the pre-rendered app). Client-only —
    # the server never calls these (they are inert no-ops there).

    @classmethod
    def mount_document(cls, document=None):
        """Client-only: mount this Page into the live document.

        The single public client mount entry (its only caller is
        ``basis.client.entrypoint``). The served document already declares its
        own mode in ``<meta name="basis-render-mode">``, so this reads it once
        and dispatches: SSR hydrates the WHOLE served document in place; CSR
        keeps the served head static and client-renders the body region.
        """
        if not IS_CLIENT:
            return None
        from pyscript import document as _document

        doc = document if document is not None else _document
        meta = doc.querySelector('meta[name="basis-render-mode"]')
        is_ssr = (
            meta is not None
            and getattr(meta, "getAttribute", lambda _: "")("content") == "ssr"
        )
        if is_ssr:
            return cls._mount_document_ssr(doc)
        return cls._mount_document_csr(doc)

    @classmethod
    def _mount_document_csr(cls, document=None):
        """Client-only: mount the page for a CSR document.

        The served static shell is kept as-is (no FOUC, no double head — the
        pyscript scripts are never re-inserted), but the Page's OWN ``<head>``
        bindings are staged and re-pointed at the LIVE ``document.head`` (the
        ``h:`` region): title, viewport meta, render-mode meta, initial-state
        script, the component-style loop and the dev-mode meta. The ``<body>``
        chrome (the user stylesheet ``<link>``s) is not a Page binding in CSR —
        it is server-assembled at the ``basis:user-stylesheets`` anchor and
        adopted as static body.

        The app itself is client-RENDERED, not hydrated: the staged Page's
        ``__element__`` already points at the live ``<html>``, so
        ``mount_root_app()`` mounts the root into the LIVE ``document.body``
        under its host tag — the same body shape SSR pre-renders. Returns the
        mounted root component (or ``None`` for a static page).

        ``document`` is the caller's PyScript ``document`` (this module is
        server-importable, so it cannot import ``pyscript`` at module scope);
        it is required on the client.
        """
        if not IS_CLIENT:
            return None

        from pyscript import document
        from basis.client.component import _emit_hydration_report, _hydrate_page_head
        from basis.shared.hydration import HydrationReport

        report = HydrationReport(mode="canonical")
        staged_page = _hydrate_page_head(cls, report=report, stamp_live=True)

        root_component = getattr(cls, "root_component", None)
        if root_component is not None:
            # Component styles are rendered in-tree in the served <head> (the
            # Page template's component_style_items loop, server-side) — so the
            # body mount never re-injects them. Every root mounts declaratively
            # under its host tag into the LIVE body (staged_page.__element__ ==
            # the live <html> after the head pass).
            mounted = staged_page.mount_root_app()
            _emit_hydration_report(report)
            return mounted
        # Static page — surface the (head) report and keep the staged Page (its
        # bindings point at the live head) from being collected.
        _emit_hydration_report(report)
        return staged_page

    @classmethod
    def _mount_document_ssr(cls, document=None):
        """Client-only: hydrate the WHOLE served SSR document in place.

        The Page's OWN bindings (head ``h:`` region: title / viewport meta /
        render-mode meta / initial-state script / component-style loop; body
        ``b:`` region: the user-stylesheet ``<link>`` loop) plus the mounted app
        subtree hydrate against one live map — see
        ``basis.client.component._hydrate_page_document_ssr``. Nothing is ever
        inserted into the document — the live SSR tree is adopted in place. The
        single report is surfaced once (mismatches carry their region in the id
        prefix).
        """
        if not IS_CLIENT:
            return None
        from basis.client.component import _hydrate_page_document_ssr

        return _hydrate_page_document_ssr(cls)

    def _render(self, request, initial_state_json=None, *, stamp_hydration=False, body_app=None):
        """Assemble the full HTML document (shell + initial state + head/body).

        Internal — the single server-side page-render funnel both the SSR and
        CSR engines end in; serve pages via ``PageResponse.from_page()`` /
        ``render_page()`` instead. ``stamp_hydration`` asks for the whole-page
        hydration pass (SSR only), with ``body_app`` the declaratively-mounted
        root app whose subtree joins the ``b:`` walk.
        """
        # Page-aware PyScript config: the per-page manifest is served at
        # ?url=<route> (the endpoint injects this page's bootstrap under
        # basis.bootstrap). Computed here because _render() always has the
        # request — covering SSR, CSR, and hand-rolled routes that call
        # Page._load() without one. The assignment re-renders the config
        # attribute (verified) and page_aware_config_url is idempotent.
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

            # Attach app-bound stores and run every store's per-request hook
            # (``apply_request``, e.g. ``$theme`` reading its ``basis_theme``
            # cookie) BEFORE any store is serialized: a hook that CONTRIBUTES to
            # another store (``$theme`` → ``$meta`` theme-color) must have run
            # first, and two phases keep that deterministic regardless of
            # set-iteration order.
            for name in names:
                instance = Store._registry.get(name) or Store.resolve(name)
                # App-bound stores (``_requires_app``, e.g. ``$plugins``) hold a
                # listing that requires the owning app. ``Store.resolve``
                # rebuilds a fresh instance with no ``_app``, so attach it +
                # recompute or the initial state serializes empty (the client
                # then hydrates a stale/empty view).
                attach_app_to_store(instance, request.app)
                apply_request = getattr(instance, "apply_request", None)
                if callable(apply_request):
                    try:
                        apply_request(request)
                    except Exception:
                        pass

            # Serialize every store (request hooks already applied).
            for name in names:
                instance = Store._registry.get(name) or Store.resolve(name)
                initial_state[name] = instance.serialize()
            if initial_state:
                # Script-safe JSON: the page template HTML-escapes the
                # interpolated value (``&`` → ``&amp;``), but script content is
                # NOT entity-decoded by the browser, so json.loads(textContent)
                # would hydrate the ESCAPED string. json_dumps_script_safe
                # escapes ``<``, ``>`` and ``&`` as \uXXXX sequences: they
                # survive template escaping unchanged, ``</script>`` cannot
                # break out, and json.loads decodes them back.
                initial_state_json = json_dumps_script_safe(initial_state)

        self.initial_state_json = initial_state_json

        # Assembly-time chrome: the viewport <style>, the component-style loop
        # and the dev-mode meta are owned reactive nodes of the Page template.
        # Only the user stylesheet <link>s are assembled here, by replacing a
        # trailing body comment anchor. The client pre-mount plan does not live
        # in the DOM — it is served per-page via /pyscript.json?url=<route>
        # (``basis.bootstrap``, see basis/server/bootstrap.py::page_bootstrap
        # and client/entrypoint.py).
        _replace_comment_anchors(
            self.__element__,
            "basis:user-stylesheets",
            [
                Element("link", {"rel": "stylesheet", "href": href}, [])
                for href in (getattr(self.__class__, "stylesheets", ()) or ())
            ],
        )

        # When the SSR engine asks, stamp the Page's own hydration surface over
        # the fully assembled tree — the <head> region (h:) and the <body> region
        # (b:, rooted at <body>, covering the mounted app subtree). CSR leaves
        # this off: its shell is served static and the client half-hydrates.
        if stamp_hydration:
            from basis.shared.hydration import apply_hydration_to_page

            apply_hydration_to_page(self, body_app=body_app)

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
    Component into a page without the developer writing a ``Page`` subclass.
    The synthesized class carries ``__synthesized__`` (informational only) and is
    treated exactly like a real ``Page`` subclass: in-tree ``<head>`` component
    styles, a declarative root child under its (declared or derived) host tag,
    whole-document ``h:``/``b:`` stamping. The per-page manifest lists it under
    its root COMPONENT name, so it boots through the same client driver as a real
    Page: the driver imports the component module (whose client ``@app.page``
    decoration registered the shell inputs) and rebuilds this class before
    mounting.

    Because the decoration takes no page-level ``stores``, they cannot reach the
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
