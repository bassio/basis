"""
Tests for the per-page manifest bootstrap (BOOTSTRAP-CONFIG-PLAN.md).

Covers:
* ``basis.bootstrap`` is ALWAYS present in /pyscript.json (bare or per-page).
* ``?url=<route>`` resolves the route→page registry and injects page-specific
  ``entrypoint`` / ``page_stores`` alongside the app-global ``store_modules`` /
  ``headless_modules``.
* ``app._pages`` is keyed by route and populated by ``include_page`` + ``@app.page``.
* Synthesized ``@app.page`` shells emit NO entrypoint.
* Custom ``pyscript_json_url`` is left unchanged (no ``?url=`` appended).
* ``client_modules`` stays at the manifest root.
"""
import importlib.util
import sys

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.server.bootstrap import page_bootstrap
from basis.shared.base_component import BaseComponent
from basis.shared.component import Component
from basis.shared.page import Page, page_aware_config_url
from basis.shared.store import Store


@pytest.fixture(autouse=True)
def _clean_registries():
    before = set(BaseComponent._registry)
    Store._registry.clear()
    Store._store_blueprints.clear()
    Basis._component_routes = []
    Basis._component_dirs = []
    yield
    for tag in set(BaseComponent._registry) - before:
        del BaseComponent._registry[tag]
    Store._registry.clear()
    Store._store_blueprints.clear()
    Basis._component_routes = []
    Basis._component_dirs = []


class Root(Component):
    """<div>hi</div>"""


def test_basis_bootstrap_always_present_bare_manifest():
    app = Basis()
    app.bootstrap()
    client = TestClient(app)
    r = client.get("/pyscript.json")
    assert r.status_code == 200
    payload = r.json()
    assert "basis" in payload and "bootstrap" in payload["basis"]
    assert "client_modules" in payload


def test_page_registry_populated_by_include_page():
    app = Basis()
    app.bootstrap()

    class MyPage(Page):
        root_component = Root

    app.include_page("/admin", page_cls=MyPage)
    assert app._pages["/admin"] is MyPage


def test_page_registry_populated_by_app_page():
    app = Basis()

    @app.page(path="/")
    class Home(Component):
        """<div>Hi</div>"""

    assert "/" in app._pages


def test_pyscript_json_etag_revalidates():
    """/pyscript.json is dynamic-but-bursty: content-hash ETag + no-cache so
    the browser revalidates (304) instead of re-downloading, while any real
    manifest change (page / plugin / host) still yields a fresh 200."""
    app = Basis()
    app.bootstrap()
    client = TestClient(app)

    r1 = client.get("/pyscript.json")
    assert r1.status_code == 200
    etag = r1.headers.get("etag")
    assert etag and etag.startswith('"')
    assert r1.headers.get("cache-control") == "no-cache"

    # Identical content -> 304.
    r2 = client.get("/pyscript.json", headers={"If-None-Match": etag})
    assert r2.status_code == 304


def test_pyscript_json_etag_is_page_aware():
    """Different pages carry different bodies -> different ETags; each page's
    manifest revalidates to 304 independently (no cross-page staleness)."""
    app = Basis()
    app.bootstrap()

    Store("page_store_x")

    class MyPage(Page):
        root_component = Root  # in-module component; no entrypoint emitted
        stores = ["page_store_x"]

    app.include_page("/cached", page_cls=MyPage)
    client = TestClient(app)

    bare = client.get("/pyscript.json")
    page = client.get("/pyscript.json?url=/cached")
    assert bare.status_code == page.status_code == 200
    # The page manifest carries page_stores that the bare manifest lacks, so
    # the bodies (and thus the content-hash ETags) must differ.
    assert page.json()["basis"]["bootstrap"].get("page_stores") == ["page_store_x"]
    assert page.headers.get("etag") != bare.headers.get("etag")

    # Re-requesting the page manifest with its own etag -> 304.
    again = client.get(
        "/pyscript.json?url=/cached",
        headers={"If-None-Match": page.headers["etag"]},
    )
    assert again.status_code == 304


def test_manifest_unknown_route_no_page_specific():
    app = Basis()
    app.bootstrap()
    client = TestClient(app)
    r = client.get("/pyscript.json?url=/nope")
    assert r.status_code == 200
    bootstrap = r.json()["basis"]["bootstrap"]
    assert "entrypoint" not in bootstrap
    assert "page_stores" not in bootstrap


def test_manifest_page_stores_per_route():
    app = Basis()
    app.bootstrap()

    Store("page_store_a")

    class PageA(Page):
        root_component = Root
        stores = ["page_store_a"]

    class PageB(Page):
        root_component = Root  # default-all

    app.include_page("/a", page_cls=PageA)
    app.include_page("/b", page_cls=PageB)

    client = TestClient(app)
    a = client.get("/pyscript.json?url=/a").json()["basis"]["bootstrap"]
    b = client.get("/pyscript.json?url=/b").json()["basis"]["bootstrap"]
    assert a.get("page_stores") == ["page_store_a"]
    assert "page_stores" not in b


def test_hand_rolled_route_self_registers_page_for_manifest(tmp_path):
    """A bare @app.get() route (the hand-rolled-route pattern) must still get a page-aware
    manifest: the shell appends ?url= from the request and self-registers the
    route→page mapping so the endpoint can resolve the page.

    Note: ``Page.load()`` reconstructs the class via ``initialize()``
    (``type(cls.__name__, (cls,), ...)``), so ``app._pages["/"]`` is that
    reconstructed subclass — assert by name/module, not identity.
    """
    from fastapi import Request
    from fastapi.responses import HTMLResponse

    comp = tmp_path / "components"
    comp.mkdir()
    (comp / "__init__.py").write_text("")
    home = comp / "home_page.py"
    home.write_text(
        "from basis.shared.page import Page\n"
        "from basis.shared.component import Component\n"
        "from basis.shared.store import Store\n"
        "Store('hand_rolled_store')\n"
        "class Root(Component):\n"
        "    '''<div>hi</div>'''\n"
        "class HomePage(Page):\n"
        "    root_component = Root\n"
        "    stores = ['hand_rolled_store']\n"
        "    entry_module = '/basis/client/entrypoint.py'\n"
    )
    spec = importlib.util.spec_from_file_location("components.home_page", home)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["components.home_page"] = mod
    spec.loader.exec_module(mod)

    try:
        app = Basis()
        app.bootstrap()
        app.include_components_dir("/components", str(comp), name="components")

        @app.get("/")
        async def home(request: Request):
            # Hand-rolled route served via the blessed PageResponse.from_page.
            from basis.server.responses import PageResponse
            return await PageResponse.from_page(mod.HomePage, request, render_mode="csr")

        client = TestClient(app)
        html = client.get("/").text
        # config URL is page-aware even though load() had no request.
        assert 'config="/pyscript.json?url=/"' in html
        # the shell self-registered the route → page mapping.
        assert "/" in app._pages
        # the per-page manifest resolves the page: entrypoint + page stores.
        bootstrap = client.get("/pyscript.json?url=/").json()["basis"]["bootstrap"]
        assert bootstrap["entrypoint"] == {"HomePage": "components.home_page"}
        assert bootstrap["page_stores"] == ["hand_rolled_store"]
    finally:
        sys.modules.pop("components.home_page", None)


def test_manifest_app_global_keys_without_route(tmp_path):
    app = Basis()
    app.bootstrap()
    # Simulate an auto-discovered stores/ dir + a headless component.
    app._discovered_store_modules = ["myapp.stores.state"]
    comp = tmp_path / "components"
    comp.mkdir()
    (comp / "hero_card.html").write_text("<div>hi</div>")
    app.include_components_dir("/components", str(comp), name="components")

    client = TestClient(app)
    bootstrap = client.get("/pyscript.json").json()["basis"]["bootstrap"]
    assert bootstrap["store_modules"] == ["myapp.stores.state"]
    assert bootstrap["headless_modules"] == ["components.hero_card"]


def test_manifest_entrypoint_when_page_under_component_mount(tmp_path):
    comp = tmp_path / "components"
    comp.mkdir()
    (comp / "__init__.py").write_text("")
    home = comp / "home_page.py"
    home.write_text(
        "from basis.shared.page import Page\n"
        "from basis.shared.component import Component\n"
        "class Root(Component):\n"
        "    '''<div>hi</div>'''\n"
        "class HomePage(Page):\n"
        "    root_component = Root\n"
    )
    spec = importlib.util.spec_from_file_location("components.home_page", home)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["components.home_page"] = mod
    spec.loader.exec_module(mod)

    try:
        app = Basis()
        app.bootstrap()
        app.include_components_dir("/components", str(comp), name="components")
        app.include_page("/", page_cls=mod.HomePage)

        client = TestClient(app)
        bootstrap = client.get("/pyscript.json?url=/").json()["basis"]["bootstrap"]
        assert bootstrap["entrypoint"] == {"HomePage": "components.home_page"}
    finally:
        sys.modules.pop("components.home_page", None)


def test_page_aware_config_url():
    class FakeRequest:
        url = type("URL", (), {"path": "/admin"})()

    assert page_aware_config_url("/pyscript.json", FakeRequest) == "/pyscript.json?url=/admin"
    assert page_aware_config_url("/pyscript.json", None) == "/pyscript.json"
    assert (
        page_aware_config_url("https://cdn.example.com/cfg.json", FakeRequest)
        == "https://cdn.example.com/cfg.json"
    )
    assert page_aware_config_url("/pyscript.json?x=1", FakeRequest) == "/pyscript.json?x=1"


def test_page_bootstrap_skips_synthesized_entrypoint():
    app = Basis()

    @app.page(path="/")
    class Home(Component):
        """<div>Hi</div>"""

    page_cls = app._pages["/"]
    assert page_bootstrap(app, page_cls).get("entrypoint") is None
