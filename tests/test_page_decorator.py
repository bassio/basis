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


def test_synthesized_page_not_in_entrypoint_imports():
    app = Basis()

    @app.page(path="/")
    class Home(Component):
        """<div>Hi</div>"""

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    # The synthesized class is server-side shell config only — its (unimportable)
    # name must not leak into #basis-entrypoint-imports.
    assert "HomePage" not in resp.text


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
    # render_page_ssr stamps it "ssr" so the unified client entrypoint picks
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
        page_instance = MyPage.load()
        return HTMLResponse(page_instance.render_full_page(request=request))

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
    match = re.search(
        r'<script id="basis-page-stores"[^>]*>(.*?)</script>', resp.text, re.DOTALL
    )
    assert match, "basis-page-stores script not found"
    assert json.loads(match.group(1)) == ["page_subset_store"]


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
        page_instance = MyPage.load()
        return HTMLResponse(page_instance.render_full_page(request=request))

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
        page_instance = MyPage.load()
        return HTMLResponse(page_instance.render_full_page(request=request))

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
