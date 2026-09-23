"""``StaticPage`` — the document the client never boots.

A static page renders the same chrome as :class:`Page` (doctype, viewport policy, the
``$head`` loops, the iOS metas, component styles, user stylesheets) around a
server-rendered component tree, and adds none of the client: no PyScript, no state
script, no hydration stamps, no render-mode/dev metas. *Static* means **no client**, not
"no data" — the store pipeline still runs end to end, so a page's stores collect, their
``apply_request`` hooks contribute, and ``server_load`` fires.

These tests pin the document contract, the template arithmetic that keeps ``Page``
byte-identical to the document minus two named client blocks, the refusals, and the
registration paths.
"""
import asyncio
import inspect
import re
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.server.render import render_page
from basis.shared.component import Component, scoped
from basis.shared.page import (
    Page,
    StaticPage,
    _CLIENT_HEAD,
    _CLIENT_RUNTIME,
    _PAGE_DOCUMENT,
    _STATIC_DOCUMENT,
)
from basis.shared.store import Store

ROOT_CSS = "static-root-el { color: rgb(9, 9, 9); }"


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes
    Store._registry.clear()
    Store._store_blueprints.clear()


class StaticRoot(Component):
    """A root with a stylesheet of its own, a theme provider and a server preload."""

    @scoped
    def style(self):
        """static-root-el { color: rgb(9, 9, 9); }"""

    async def server_load(self):
        self.headline = "loaded"

    def template(self):
        """
        <div class="static-root-el">
            <ui-theme-provider></ui-theme-provider>
            {headline}
        </div>
        """


class StaticDemo(StaticPage):
    title = "static demo"
    root_component = StaticRoot
    stylesheets = ("/app.css",)


def _app(page_cls=StaticDemo, path="/static"):
    app = Basis()
    app.bootstrap()
    app.include_page(path, page_cls=page_cls)
    return app


def _head_of(html: str) -> str:
    return html.split("</head>", 1)[0]


def _body_of(html: str) -> str:
    return html.split("</head>", 1)[1]


def _render(page_cls=StaticDemo, *, app=None, **request_attrs):
    """Render a static page through the engine, with a request only as real as needed."""
    app = app or _app(page_cls)
    request = SimpleNamespace(
        app=app,
        cookies={},
        url=SimpleNamespace(path="/static"),
        **request_attrs,
    )
    return asyncio.run(render_page(request, page_cls))


# ---------------------------------------------------------------------------
# The document contract
# ---------------------------------------------------------------------------

def _style_element(head: str, component: str) -> str:
    """The head ``<style data-component-class="…">`` element for *component*."""
    match = re.search(
        rf'<style[^>]*data-component-class="{component}"[^>]*>(.*?)</style>',
        head,
        re.S,
    )
    assert match is not None, f"no in-tree head style for {component}"
    return match.group(0)


def test_a_static_page_renders_the_chrome_and_the_tree():
    html = _render()
    head = _head_of(html)

    assert html.startswith("<!DOCTYPE html>")
    assert f'<meta name="viewport" content="{Page.viewport}" />' in head
    # The framework's document-level mobile base CSS, same block Page ships.
    assert "-webkit-text-size-adjust" in head
    assert 'id="basis-viewport"' in head
    # Component styles render in-tree in the head, exactly as they do for a Page.
    assert ROOT_CSS in _style_element(head, "StaticRoot")
    # $head.metas / $head.links: the theme's theme-color comes from its apply_request
    # hook, so its presence is the proof that the store pipeline ran.
    assert 'name="theme-color"' in head
    # The iOS home-screen metas ride along (inert until installed).
    assert 'name="apple-mobile-web-app-capable"' in head
    # The theme provider is part of the server-rendered tree, tokens included.
    assert 'id="theme-provider"' in html
    assert "--bg-primary:" in html
    # The tree is server-rendered, including what server_load set on it.
    assert 'class="static-root-el"' in html
    assert "loaded" in html
    # User stylesheets are assembled at the trailing body anchor, as for a Page.
    body = _body_of(html)
    assert 'href="/app.css"' in body
    assert body.index('href="/app.css"') > body.index("static-root-el")


def test_a_static_page_renders_no_client_artefact():
    html = _render()

    for absent in (
        "/pyscript",
        "<script",
        "basis-initial-state",
        "data-hydration-id",
        "basis-render-mode",
        "basis-dev-mode",
        "entry_module",
    ):
        assert absent not in html, absent


def test_a_static_page_gets_the_head_links_a_plugin_contributes():
    from basis.plugins.mobile import PwaStore

    PwaStore("pwa", title="Myapp")
    html = _render(app=_app())
    head = _head_of(html)

    assert 'rel="manifest" href="/manifest.webmanifest"' in head
    # No stylesheet link beyond the page's own: a static page must not fetch CSS it
    # did not ask for.
    assert head.count("rel=\"stylesheet\"") == 0
    assert 'rel="icon"' in head


def test_a_static_page_with_no_root_renders_chrome_only():
    class ChromeOnly(StaticPage):
        title = "no root"

    html = _render(ChromeOnly, app=_app(ChromeOnly))

    assert html.startswith("<!DOCTYPE html>")
    assert "<script" not in html
    assert 'class="static-root-el"' not in html


def test_a_static_page_honours_its_store_subset():
    class StyleContributor(Store):
        """Contributes a head style only when the page actually collects it."""

        def apply_request(self, request) -> None:
            head = Store._registry.get("head")
            if head is not None:
                head.add_style(":root { --contributed: 1; }")

    StyleContributor("style_contributor")

    class WholeCatalogue(StaticPage):
        root_component = StaticRoot

    class Strict(WholeCatalogue):
        stores = ["head"]

    assert "--contributed: 1" in _render(WholeCatalogue)
    assert "--contributed: 1" not in _render(Strict, app=_app(Strict))


# ---------------------------------------------------------------------------
# Template arithmetic — the split is a subtraction, not a second document
# ---------------------------------------------------------------------------

def test_each_client_block_occurs_exactly_once_in_the_page_document():
    assert _PAGE_DOCUMENT.count(_CLIENT_HEAD) == 1
    assert _PAGE_DOCUMENT.count(_CLIENT_RUNTIME) == 1


def test_page_renders_the_whole_document_and_static_the_subtraction():
    assert Page.__templatestr__ == _PAGE_DOCUMENT
    assert StaticPage.__templatestr__ == _STATIC_DOCUMENT
    assert StaticPage.__templatestr__ == _PAGE_DOCUMENT.replace(
        _CLIENT_HEAD, "", 1
    ).replace(_CLIENT_RUNTIME, "", 1)
    for absent in (_CLIENT_HEAD, _CLIENT_RUNTIME, "basis-render-mode", "basis-initial-state"):
        assert absent not in StaticPage.__templatestr__


def test_the_client_blocks_are_named_client_runtime_pieces():
    """They must stay disjoint: the subtraction removes one of each, so an overlap
    would take part of the document with it."""
    assert _CLIENT_HEAD not in _CLIENT_RUNTIME
    assert _CLIENT_RUNTIME not in _CLIENT_HEAD
    assert "basis-render-mode" in _CLIENT_HEAD
    assert "pyscript" in _CLIENT_RUNTIME and "basis-initial-state" in _CLIENT_RUNTIME


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------

def test_include_page_refuses_render_mode_for_a_static_page():
    app = Basis()
    app.bootstrap()

    with pytest.raises(ValueError, match="render_mode"):
        app.include_page("/static-csr", page_cls=StaticDemo, render_mode="csr")


def test_the_engine_refuses_render_mode_for_a_static_page():
    with pytest.raises(ValueError, match="StaticPage"):
        asyncio.run(render_page(None, StaticDemo, render_mode="ssr"))
    with pytest.raises(ValueError, match="StaticPage"):
        asyncio.run(render_page(None, StaticDemo, render_mode="csr"))


def test_a_component_decorated_with_a_static_page_cls_is_refused():
    """``@app.page`` is the client-boot sugar: a static page has no driver to replay its
    recipe, so the decoration must send the author to ``include_page``."""

    class Rootless(StaticPage):
        pass

    app = Basis()
    app.bootstrap()

    with pytest.raises(ValueError, match="no client"):
        @app.page(path="/decorated", page_cls=Rootless)
        class DecoratedRoot(Component):
            template = "<div>hi</div>"


def test_the_client_page_shim_recognises_a_static_page():
    """Source-level guard (the shim exists only under ``IS_CLIENT``, which these tests
    never set): a page subclass is not a root component to annotate."""
    from basis.shared import component as component_module

    src = inspect.getsource(component_module)
    assert "from basis.shared.page import StaticPage as _StaticPageBase" in src
    assert "issubclass(component, _StaticPageBase)" in src


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

def test_include_page_serves_a_static_document():
    client = TestClient(_app())
    response = client.get("/static")

    assert response.status_code == 200
    assert response.text.startswith("<!DOCTYPE html>")
    assert "<script" not in response.text


def test_serve_accepts_a_static_page():
    app = Basis()

    @app.serve("/terms")
    class Terms(StaticPage):
        title = "Terms"
        root_component = StaticRoot

    html = TestClient(app).get("/terms").text

    assert "static-root-el" in html
    assert "<script" not in html


def test_a_static_page_is_not_registered_as_a_boot_plan():
    """``/pyscript.json?url=<route>`` resolves through ``app._pages``: a page with no
    client has no bootstrap to hand out, so it must not appear there — and the manifest
    it would have been served from carries no entrypoint for that route either."""
    app = _app()
    client = TestClient(app)

    assert "/static" not in app._pages
    manifest = client.get("/pyscript.json?url=/static")
    assert manifest.status_code == 200
    assert "entrypoint" not in manifest.json()["basis"]["bootstrap"]
