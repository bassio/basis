"""
Tests for the Page / root-component API:

* ``@app.page`` decorates a root Component, synthesizes a page, serves it at ``path``.
* ``@app.page`` rejects a ``Page`` subclass (a Page is the shell, not a root).
* ``@app.page`` rejects a custom shell that already declares ``root_component``/``stores``.
* ``app.include_page(path, page_cls=...)`` registers a Page; also usable as a decorator.
* ``include_page`` requires a Page subclass.
* ``Page`` defaults: ``root_component = None`` (abstract/static shell), ``stores = []``.
* Synthesized pages are NOT emitted into ``#basis-entrypoint-imports``.
* SSR pages carry a ``<meta name="basis-render" content="ssr">`` marker (the
  unified client entrypoint dispatches on it); a strict page store subset is
  emitted as ``#basis-page-stores`` and the framework control-plane store
  (``$plugins``) is always serialized on CSR (``$regions`` is a plugin-provided
  store — serialized by default, or listed in ``Page.stores`` explicitly).
"""
import json
import re

import pytest
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.store import Store


def test_page_decorator_serves_at_root_by_default():
    app = Basis()

    @app.page
    class Hello(Component):
        """<div>Hi {name}</div>"""
        name = "World"

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Hi World" in resp.text


def test_page_decorator_serves_at_custom_path():
    app = Basis()

    @app.page(path="/hello")
    class Hello(Component):
        """<div>Hi {name}</div>"""
        name = "World"

    client = TestClient(app)
    resp = client.get("/hello")
    assert resp.status_code == 200
    assert "Hi World" in resp.text
    # Not mounted at the default path.
    assert client.get("/").status_code == 404


def test_page_decorator_returns_component_class():
    app = Basis()

    @app.page(path="/")
    class Hello(Component):
        """<div>Hi</div>"""

    # The decorator returns the decorated class, not the app.
    assert Hello is not app
    assert issubclass(Hello, Component)


def test_page_decorator_rejects_page_subclass():
    from basis.shared.page import Page

    app = Basis()

    class MyPage(Page):
        pass

    with pytest.raises(TypeError, match="is a Page, not a root component"):
        app.page(MyPage)


def test_page_decorator_rejects_shell_with_own_root():
    from basis.shared.page import Page

    app = Basis()

    class Root(Component):
        """<div>hi</div>"""

    class Shell(Page):
        root_component = Root

    with pytest.raises(ValueError, match="already declares"):
        app.page(Root, path="/x", page_cls=Shell)


def test_page_decorator_rejects_shell_with_stores():
    from basis.shared.page import Page

    app = Basis()

    class Root(Component):
        """<div>hi</div>"""

    class Shell(Page):
        stores = ["s"]

    with pytest.raises(ValueError, match="already declares"):
        app.page(Root, path="/x", page_cls=Shell)


def test_include_page_requires_a_page_subclass():
    app = Basis()
    app.bootstrap()

    class NotAPage(Component):
        """<div>hi</div>"""

    with pytest.raises(TypeError, match="requires a Page subclass"):
        app.include_page("/x", page_cls=NotAPage)


def test_include_page_declarative_root_from_page_cls():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>Declarative root</div>"""

    class MyPage(Page):
        title = "Declarative"
        root_component = Root
        entry_module = "/test_root.py"

    app.include_page("/dec", page_cls=MyPage)

    client = TestClient(app)
    resp = client.get("/dec")
    assert resp.status_code == 200
    assert "Declarative root" in resp.text
    assert "<title>Declarative</title>" in resp.text


def test_include_page_decorator_form():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>Decorator root</div>"""

    @app.include_page("/decorator")
    class DecoratorPage(Page):
        title = "Decorator"
        root_component = Root
        entry_module = "/test_root.py"

    # include_page returns the Page class so the name stays bound to it.
    assert issubclass(DecoratorPage, Page)

    client = TestClient(app)
    resp = client.get("/decorator")
    assert resp.status_code == 200
    assert "Decorator root" in resp.text
    assert "<title>Decorator</title>" in resp.text


def test_page_defaults_are_abstract_shell():
    from basis.shared.page import Page

    assert Page.root_component is None
    assert Page.stores == []


def test_page_subclass_carries_root_and_stores():
    from basis.shared.page import Page

    class Root(Component):
        """<div>hi</div>"""

    class Concrete(Page):
        root_component = Root
        stores = ["one", "two"]

    assert Concrete.root_component is Root
    assert Concrete.stores == ["one", "two"]


def test_synthesized_page_not_in_manifest_entrypoint():
    app = Basis()

    @app.page(path="/")
    class Home(Component):
        """<div>Hi</div>"""

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    # The synthesized class is server-side shell config only — its (unimportable)
    # name must not leak into the per-page manifest's basis.bootstrap.entrypoint.
    assert "HomePage" not in resp.text
    manifest = client.get("/pyscript.json?url=/")
    assert manifest.status_code == 200
    assert "entrypoint" not in manifest.json()["basis"]["bootstrap"]


def test_ssr_page_emits_render_mode_marker():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>hi</div>"""

    class MyPage(Page):
        root_component = Root
        entry_module = "/test_root.py"

    app.include_page("/ssr", page_cls=MyPage)

    client = TestClient(app)
    resp = client.get("/ssr")
    assert resp.status_code == 200
    # The render-mode meta is a reactive template binding on the Page shell;
    # render_page stamps it "ssr" so the unified client entrypoint picks
    # the SSR hydration mount. (Void elements self-close.)
    assert '<meta name="basis-render-mode" content="ssr" />' in resp.text


def test_csr_page_renders_render_mode_csr():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>hi</div>"""

    class MyPage(Page):
        root_component = Root
        entry_module = "/test_root.py"

    @app.get("/csr")
    async def csr(request: Request):
        from basis.server.responses import PageResponse
        return await PageResponse.from_page(MyPage, request, render_mode="csr")

    client = TestClient(app)
    resp = client.get("/csr")
    assert resp.status_code == 200
    # CSR keeps the class default — the client treats anything but "ssr" as a
    # plain client mount.
    assert '<meta name="basis-render-mode" content="csr" />' in resp.text


def test_page_subset_emits_page_store_names_for_client():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class S(Store):
        def __init__(self, name):
            super().__init__(name)
            self.v = 1

    S("page_subset_store")

    class Root(Component):
        """<div>hi</div>"""

    class MyPage(Page):
        root_component = Root
        stores = ["page_subset_store"]
        entry_module = "/test_root.py"

    app.include_page("/p", page_cls=MyPage)

    client = TestClient(app)
    resp = client.get("/p")
    assert resp.status_code == 200
    # The page's strict store subset is served per-page via the manifest.
    manifest = client.get("/pyscript.json?url=/p")
    assert manifest.status_code == 200
    assert manifest.json()["basis"]["bootstrap"]["page_stores"] == ["page_subset_store"]


def test_csr_page_always_serializes_framework_stores_with_strict_subset():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class S(Store):
        def __init__(self, name):
            super().__init__(name)
            self.v = 1

    S("csr_subset_store")

    class Root(Component):
        """<div>hi</div>"""

    class MyPage(Page):
        root_component = Root
        stores = ["csr_subset_store"]
        entry_module = "/test_root.py"

    @app.get("/csr")
    async def csr(request: Request):
        from basis.server.responses import PageResponse
        return await PageResponse.from_page(MyPage, request, render_mode="csr")

    client = TestClient(app)
    resp = client.get("/csr")
    assert resp.status_code == 200

    match = re.search(
        r'<script id="basis-initial-state"[^>]*>(.*?)</script>',
        resp.text,
        re.DOTALL,
    )
    assert match, "basis-initial-state script not found"
    state = json.loads(match.group(1))

    # The page's explicit subset is serialized...
    assert "csr_subset_store" in state
    # ...and the framework control-plane store hydrates even though the page
    # did not list it (it must exist on every page, not just default-all ones).
    assert "plugins" in state
    # $regions is a plugin-provided store, NOT a framework control plane: it is
    # not force-serialized for a strict subset unless the page lists it.
    assert "regions" not in state


def test_csr_page_serializes_regions_when_listed_in_strict_subset():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class S(Store):
        def __init__(self, name):
            super().__init__(name)
            self.v = 1

    # Unique name: Store blueprints persist across tests in this file (no
    # per-test registry reset here), so a second local S with the same name
    # would trip the conflict-aware redeclaration guard.
    S("csr_subset_store_b")

    class Root(Component):
        """<div>hi</div>"""

    class MyPage(Page):
        root_component = Root
        stores = ["csr_subset_store_b", "regions"]
        entry_module = "/test_root.py"

    @app.get("/csr")
    async def csr(request: Request):
        from basis.server.responses import PageResponse
        return await PageResponse.from_page(MyPage, request, render_mode="csr")

    client = TestClient(app)
    resp = client.get("/csr")
    assert resp.status_code == 200

    match = re.search(
        r'<script id="basis-initial-state"[^>]*>(.*?)</script>',
        resp.text,
        re.DOTALL,
    )
    assert match, "basis-initial-state script not found"
    state = json.loads(match.group(1))

    # Listing "regions" in the page's strict subset serializes the $regions
    # projection (the regions plugin registered its store at boot).
    assert "regions" in state


# ---------------------------------------------------------------------------
# @app.serve — the FastAPI-shaped page decorator
# ---------------------------------------------------------------------------

def test_serve_decorates_page_and_serves_at_path():
    from basis.shared.page import Page

    app = Basis()

    class Root(Component):
        """<div>Served root</div>"""

    @app.serve("/about")
    class AboutPage(Page):
        title = "About"
        root_component = Root
        entry_module = "/test_root.py"

    assert issubclass(AboutPage, Page)

    client = TestClient(app)
    resp = client.get("/about")
    assert resp.status_code == 200
    assert "Served root" in resp.text
    assert "<title>About</title>" in resp.text


def test_serve_imperative_form():
    from basis.shared.page import Page

    app = Basis()

    class Root(Component):
        """<div>Home root</div>"""

    class HomePage(Page):
        title = "Home"
        root_component = Root
        entry_module = "/test_root.py"

    app.serve("/")(HomePage)

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Home root" in resp.text


def test_serve_same_page_at_multiple_urls():
    from basis.shared.page import Page

    app = Basis()

    class Root(Component):
        """<div>Shared root</div>"""

    class SharedPage(Page):
        title = "Shared"
        root_component = Root
        entry_module = "/test_root.py"

    app.serve("/")(SharedPage)
    app.serve("/mirror")(SharedPage)

    client = TestClient(app)
    assert client.get("/").status_code == 200
    assert client.get("/mirror").status_code == 200


def test_serve_on_component_synthesizes_quickstart_page():
    app = Basis()

    @app.serve("/")
    class Hello(Component):
        """<div>Hi {name}</div>"""
        name = "World"

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Hi World" in resp.text


def test_include_page_serves_csr_when_render_mode_csr():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>ROOTMARKER</div>"""

    class MyPage(Page):
        root_component = Root
        entry_module = "/test_root.py"

    app.include_page("/csr", page_cls=MyPage, render_mode="csr")

    client = TestClient(app)
    resp = client.get("/csr")
    assert resp.status_code == 200
    # CSR: the shell carries the csr marker and the root is NOT server-rendered.
    assert '<meta name="basis-render-mode" content="csr" />' in resp.text
    assert "ROOTMARKER" not in resp.text


def test_serve_render_mode_kwarg_overrides_class_override():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>hi</div>"""

    class MyPage(Page):
        root_component = Root
        render_mode = "csr"
        entry_module = "/test_root.py"

    # Class override (csr) honored when no kwarg...
    app.include_page("/a", page_cls=MyPage)
    # ...explicit kwarg wins over the class override.
    app.include_page("/b", page_cls=MyPage, render_mode="ssr")

    client = TestClient(app)
    a = client.get("/a")
    b = client.get("/b")
    assert '<meta name="basis-render-mode" content="csr" />' in a.text
    assert '<meta name="basis-render-mode" content="ssr" />' in b.text


def test_serve_same_page_two_urls_different_render_modes():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>dual root</div>"""

    class DualPage(Page):
        root_component = Root
        entry_module = "/test_root.py"

    app.serve("/full")(DualPage)                      # ssr default
    app.serve("/lite", render_mode="csr")(DualPage)

    client = TestClient(app)
    full = client.get("/full")
    lite = client.get("/lite")
    assert '<meta name="basis-render-mode" content="ssr" />' in full.text
    assert "dual root" in full.text
    assert '<meta name="basis-render-mode" content="csr" />' in lite.text
    assert "dual root" not in lite.text


# ---------------------------------------------------------------------------
# PageResponse — the page-aware HTMLResponse
# ---------------------------------------------------------------------------

def test_page_response_from_page_ssr_and_csr():
    from basis.server.responses import PageResponse
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>resp root</div>"""

    class RespPage(Page):
        root_component = Root
        entry_module = "/test_root.py"

    @app.get("/ssr-resp")
    async def ssr(request: Request):
        return await PageResponse.from_page(RespPage, request, render_mode="ssr")

    @app.get("/csr-resp")
    async def csr(request: Request):
        return await PageResponse.from_page(RespPage, request, render_mode="csr")

    client = TestClient(app)
    ssr = client.get("/ssr-resp")
    csr = client.get("/csr-resp")
    assert ssr.status_code == 200
    assert '<meta name="basis-render-mode" content="ssr" />' in ssr.text
    assert "resp root" in ssr.text
    assert csr.status_code == 200
    assert '<meta name="basis-render-mode" content="csr" />' in csr.text
    assert "resp root" not in csr.text


def test_resolve_render_mode_precedence():
    from basis.server.render import _resolve_render_mode
    from basis.shared.page import Page

    class DefaultPage(Page):
        pass

    class CsrPage(Page):
        render_mode = "csr"

    # kwarg wins over everything.
    assert _resolve_render_mode(DefaultPage, "csr") == "csr"
    assert _resolve_render_mode(CsrPage, "ssr") == "ssr"
    # explicit class override honored when no kwarg.
    assert _resolve_render_mode(CsrPage, None) == "csr"
    # inherited base default is NOT treated as an override → route default ssr.
    assert _resolve_render_mode(DefaultPage, None) == "ssr"


def test_page_response_rejects_unknown_render_mode():
    import asyncio

    from basis.server.responses import PageResponse
    from basis.shared.page import Page

    class P(Page):
        pass

    # The validation runs in render_page (inside the async factory), before any
    # request is touched, so it can be exercised without a real request.
    with pytest.raises(ValueError, match="render_mode must be"):
        asyncio.run(PageResponse.from_page(P, None, render_mode="bogus"))


# ---------------------------------------------------------------------------
# Page.load — unified store instantiation (SSR and CSR)
# ---------------------------------------------------------------------------

@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_page_load_instantiates_stores_without_ssr_flag():
    from basis.shared.page import Page

    class S(Store):
        def __init__(self, name):
            super().__init__(name)
            self.v = 7

    S("csr_load_store")
    Store._registry.clear()

    class MyPage(Page):
        stores = ["csr_load_store"]

    # load() with no ssr flag still instantiates the page's stores.
    MyPage.load()
    store = Store._registry.get("csr_load_store")
    assert isinstance(store, S)
    assert store.v == 7


def test_client_basis_shim_mirrors_serve_onto_page():
    """The client-side Basis shim must expose ``serve`` (mirroring ``page``) so
    the single-file ``@app.serve`` component quickstart hydrates in the browser
    (the component file is the PyScript boot module; the shim is only defined
    when IS_CLIENT, so this is a source-level guard)."""
    import inspect

    import basis.shared.component as component_mod

    src = inspect.getsource(component_mod)
    assert "def serve(self, *args, **kwargs):" in src
    assert "self.page(component, **kwargs)" in src
