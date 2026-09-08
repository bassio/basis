"""
Tests for the M1.1 mobile viewport & base-CSS changes (ROADMAP-MOBILE.md,
MOBILE-M1.1-PLAN.md):

* ``Page.viewport`` is a class attribute; the rendered viewport ``<meta>``
  carries the mobile-correct default (``viewport-fit=cover`` +
  ``interactive-widget=resizes-content``) in BOTH SSR and CSR.
* A ``Page`` subclass may override ``viewport`` to opt out — the rendered meta
  reflects the subclass value exactly.
* ``Page._render`` injects the framework mobile base CSS as a light-DOM
  ``<style id="basis-viewport">`` into ``<head>`` (component styles live in
  shadow roots and cannot reach ``html``/``body``); it is present and intact
  (not binding-parsed/escaped) in SSR and CSR output.
"""
import re

from fastapi import Request
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page

DEFAULT_VIEWPORT = (
    "width=device-width, initial-scale=1.0, viewport-fit=cover, "
    "interactive-widget=resizes-content"
)


def _viewport_of(html: str) -> str | None:
    m = re.search(r'<meta name="viewport" content="([^"]+)"', html)
    return m.group(1) if m else None


def _build_app() -> tuple[Basis, str, str]:
    """Return (app, ssr_url, csr_url) serving the same page in both modes."""
    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>hi</div>"""

    class MyPage(Page):
        root_component = Root
        entry_module = "/test_mobile_root.py"

    app.include_page("/mobile-ssr", page_cls=MyPage)

    @app.get("/mobile-csr")
    async def csr(request: Request):
        from basis.server.responses import PageResponse

        return await PageResponse.from_page(MyPage, request, render_mode="csr")

    return app, "/mobile-ssr", "/mobile-csr"


def test_viewport_default_rendered_in_ssr_and_csr():
    app, ssr_url, csr_url = _build_app()
    client = TestClient(app)

    assert client.get(ssr_url).status_code == 200
    assert client.get(csr_url).status_code == 200

    ssr = client.get(ssr_url).text
    csr = client.get(csr_url).text
    assert _viewport_of(ssr) == DEFAULT_VIEWPORT
    assert _viewport_of(csr) == DEFAULT_VIEWPORT


def test_viewport_class_attribute_override_is_respected():
    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>hi</div>"""

    class NarrowPage(Page):
        root_component = Root
        entry_module = "/test_mobile_root.py"
        # Opt-out example: a full-screen reader page that wants the keyboard to
        # only resize the visual viewport, and no safe-area fit.
        viewport = "width=device-width, interactive-widget=resizes-visual"

    app.include_page("/mobile-narrow", page_cls=NarrowPage)
    client = TestClient(app)

    html = client.get("/mobile-narrow").text
    assert client.get("/mobile-narrow").status_code == 200
    assert (
        _viewport_of(html)
        == "width=device-width, interactive-widget=resizes-visual"
    )


def test_mobile_base_style_block_injected_into_head():
    app, ssr_url, csr_url = _build_app()
    client = TestClient(app)

    for url in (ssr_url, csr_url):
        html = client.get(url).text
        # The viewport style is an in-tree <head> binding node (§4.1 P3) so it
        # carries a data-hydration-id after the id attribute — match on the id
        # prefix, not the exact open tag.
        assert '<style id="basis-viewport"' in html
        # Must live in <head>, not <body>.
        head = html.split("</head>", 1)[0]
        assert '<style id="basis-viewport"' in head


def test_mobile_base_style_content_is_intact():
    app, ssr_url, _ = _build_app()
    client = TestClient(app)

    html = client.get(ssr_url).text
    # Everything after the id prefix up to the tag's closing '>' then </style>.
    tail = html.split('<style id="basis-viewport"', 1)[1]
    body = tail.split(">", 1)[1].split("</style>", 1)[0]

    # The CSS must survive round-trip: not binding-parsed (no [Error: ...]),
    # not HTML-escaped (braces intact), and it carries the expected rules.
    assert "[Error" not in body
    assert "{" in body and "}" in body
    assert "-webkit-text-size-adjust: 100%" in body
    assert "touch-action: manipulation" in body
    # Rules are scoped to interactive controls — no blanket pinch-zoom kill.
    assert 'button, a, input, select, textarea, [role="button"]' in body


# --- iOS standalone meta (Decision G) --------------------------------------

def _serve_page(page_cls, path="/apple-page"):
    app = Basis()
    app.bootstrap()
    app.include_page(path, page_cls=page_cls)
    return TestClient(app), path


def test_apple_web_app_meta_present_by_default():
    """The iOS home-screen meta ships by default in SSR + CSR (inert until the
    page is added to the home screen)."""
    app, ssr_url, csr_url = _build_app()
    client = TestClient(app)
    for url in (ssr_url, csr_url):
        html = client.get(url).text
        head = html.split("</head>", 1)[0]
        assert 'name="apple-mobile-web-app-capable" content="yes"' in head
        assert 'name="apple-mobile-web-app-title" content="Basis App"' in head
        # black-translucent rides on the D6 safe-area guard (the default).
        assert (
            'name="apple-mobile-web-app-status-bar-style" content="black-translucent"'
            in head
        )


def test_apple_web_app_opt_out_drops_all_tags():
    class Root(Component):
        """<div>hi</div>"""

    class NoApplePage(Page):
        root_component = Root
        entry_module = "/test_apple_root.py"
        apple_web_app = False

    client, url = _serve_page(NoApplePage)
    html = client.get(url).text
    assert 'name="apple-mobile-web-app-capable"' not in html
    assert 'name="apple-mobile-web-app-title"' not in html
    assert 'name="apple-mobile-web-app-status-bar-style"' not in html


def test_apple_status_bar_style_is_overridable():
    """A document-flow page keeps the tags but opts into an opaque status bar."""
    class Root(Component):
        """<div>hi</div>"""

    class OpaqueStatusPage(Page):
        root_component = Root
        entry_module = "/test_apple_root.py"
        apple_status_bar_style = "default"

    client, url = _serve_page(OpaqueStatusPage)
    html = client.get(url).text
    assert 'name="apple-mobile-web-app-capable" content="yes"' in html
    assert 'name="apple-mobile-web-app-status-bar-style" content="default"' in html
