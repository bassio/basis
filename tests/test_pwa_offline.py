"""The offline fallback page: the document a navigation lands on with no network.

It exists for exactly one situation — the worker has nothing to serve and the server is
unreachable — so the contracts worth asserting are the ones that situation depends on: it
is served without a runtime, it is precached, it wears the app's own theme and head links,
and it asks for nothing it would have to fetch.

It is a ``StaticPage``, so those are the framework's page chrome and the app's stores
rather than a document written out by the mobile plugin: the tests below check the page,
not a hand-rolled copy of one.
"""
import json
import re

import pytest
from fastapi.testclient import TestClient

from basis.plugins.mobile import PwaStore
from basis.plugins.mobile.pwa import OFFLINE_URL
from basis.plugins.mobile.pwa.offline import OfflinePage
from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page, StaticPage
from basis.shared.store import Store


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


def _boot_app():
    app = Basis()
    app.bootstrap()

    class OfflineRoot(Component):
        template = "<div>hi</div>"

    class DemoPage(Page):
        title = "demo"
        root_component = OfflineRoot

    app.include_page("/demo", page_cls=DemoPage)
    return app


def _app(**declaration):
    PwaStore("pwa", **declaration)
    return _boot_app()


def _dark() -> dict:
    """The theme cookie a dark-mode user carries (the ``$theme`` store's own shape)."""
    return {"basis_theme": json.dumps({"active_theme": "basis", "dark_mode": True})}


def _head_of(html: str) -> str:
    return html.split("</head>", 1)[0]


def test_an_app_that_declared_nothing_has_no_fallback():
    app = _boot_app()
    assert TestClient(app).get(OFFLINE_URL).status_code == 404


def test_turning_offline_off_takes_the_fallback_with_it():
    """The declaration's switch covers the whole worker story: no worker means no
    navigation ever falls back to this page, so serving it would be an unlinked page."""
    app = _app(offline=False)
    assert TestClient(app).get(OFFLINE_URL).status_code == 404
    assert TestClient(app).get("/manifest.webmanifest").status_code == 200


def test_the_document_needs_no_runtime_and_no_server():
    app = _app(title="Myapp", start_url="/app")
    client = TestClient(app)
    page = client.get(OFFLINE_URL).text

    assert client.get(OFFLINE_URL).headers["content-type"].startswith("text/html")
    assert "<title>Offline</title>" in page
    # The card: whose app this is, and the way back into it.
    assert '<a href="/app">' in page
    assert "Myapp needs a connection" in page
    assert "offline" in page.lower()
    # No PyScript, no serialized state, no hydration surface, no scripts at all: the
    # page that stands in for a boot must not depend on one.
    for absent in (
        "/pyscript",
        "<script",
        "basis-initial-state",
        "data-hydration-id",
        "basis-render-mode",
    ):
        assert absent not in page, absent


def test_the_theme_owns_the_colors():
    """Nothing here resolves a color of its own: the card reads the theme's ``--*``
    tokens, and the theme decides light or dark — so a dark-mode install gets a dark
    fallback (and a dark browser-chrome color) without the plugin painting anything."""
    app = _app(title="Myapp")
    client = TestClient(app)

    light = client.get(OFFLINE_URL).text
    dark = client.get(OFFLINE_URL, cookies=_dark()).text

    # The token block is the theme provider's, in the page's own tree.
    assert "--bg-primary: light-dark(#F6F6F7, #1B2029)" in light
    assert "color-scheme: light" in light
    assert "color-scheme: dark" in dark
    # The card's own rules read those tokens rather than inventing colors.
    assert "background: var(--bg-primary" in light
    assert "var(--safe-area-top, env(safe-area-inset-top" in light
    # theme-color follows the mode (the theme's $head contribution, not an inline meta).
    assert 'name="theme-color" content="#f6f6f7"' in light
    assert 'name="theme-color" content="#1b2029"' in dark


def test_the_head_links_come_from_the_plugins():
    """The fallback is one of the app's pages, so it wears the app's head: the manifest
    and icon links the mobile plugin contributes, and the theme's chrome color."""
    app = _app(title="Myapp")
    client = TestClient(app)
    head = _head_of(client.get(OFFLINE_URL).text)

    assert 'rel="manifest" href="/manifest.webmanifest"' in head
    assert 'rel="icon"' in head
    assert client.get("/manifest.webmanifest").status_code == 200


def test_the_fallback_asks_for_no_stylesheet():
    """A stylesheet that has to be fetched is a stylesheet that may not be there, so the
    page inherits the framework default (no user stylesheets) rather than an app's."""
    app = _app(title="Myapp")
    page = TestClient(app).get(OFFLINE_URL).text

    assert OfflinePage.stylesheets == ()
    assert 'rel="stylesheet"' not in page
    assert "<link" in page  # the manifest/icons above — present, but inline CSS only


def test_the_page_chrome_comes_from_the_framework_not_from_a_copy():
    """Its viewport policy and document-level mobile CSS are read off ``StaticPage``
    rather than restated here, so a notched phone gets the same ``viewport-fit=cover`` —
    and the same ``--page-gutter``/``--safe-area-*`` padding convention — as every other
    page. A local copy would be a policy that drifts the first time either changes.
    """
    app = _app(title="Myapp")
    page = TestClient(app).get(OFFLINE_URL).text

    assert f'<meta name="viewport" content="{StaticPage.viewport}" />' in page
    # The mobile base CSS ships whole (it is document-level, theme-agnostic and small).
    assert "-webkit-text-size-adjust: 100%" in page
    assert "--page-gutter" in page
    # …and the card pads with the house pattern: gutter + safe-area token.
    assert "var(--page-gutter, 1.5rem) + var(--safe-area-top, env(safe-area-inset-top" in page


def test_the_declared_title_is_escaped():
    """The declaration is data: a title with markup in it must not become markup."""
    app = _app(title="My <script>app")

    page = TestClient(app).get(OFFLINE_URL).text

    assert "<script>app" not in page
    assert "My &lt;script&gt;app" in page


def test_the_document_revalidates_instead_of_being_re_sent():
    app = _app(title="Myapp")
    client = TestClient(app)

    first = client.get(OFFLINE_URL)
    again = client.get(OFFLINE_URL, headers={"if-none-match": first.headers["etag"]})

    assert again.status_code == 304


def test_the_fallback_is_precached():
    """A fallback fetched from the network is not a fallback."""
    app = _app(title="Myapp")
    body = TestClient(app).get("/service-worker.js").text
    config = json.loads(re.search(r"^const BASIS = (\{.*\});$", body, re.MULTILINE).group(1))

    assert config["offline"] == OFFLINE_URL
    assert OFFLINE_URL in config["precache"]
