"""The plugin's head links — the manifest and the icons, as the browser sees them.

The manifest link and the icon links are one decision, and they are only useful if the URLs
behind them answer: a ``<link rel="manifest">`` pointing at a 404 is worse than no link at
all, so these tests check the head *and* the route behind each href.

The links are contributed per request (``PwaStore.apply_request``), so an app that never
declared a PWA must have a head with no contribution at all, and a page that lists its
stores explicitly must still get them.
"""
import json

import pytest
from fastapi.testclient import TestClient

from basis.plugins.mobile import PwaStore
from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page
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


def _boot_app(stores: list | None = None):
    app = Basis()
    app.bootstrap()
    declared = list(stores or [])

    class LinksRoot(Component):
        template = "<div>hi</div>"

    class LinksPage(Page):
        title = "links"
        root_component = LinksRoot
        stores = declared

    app.include_page("/demo", page_cls=LinksPage)
    return app


def _app(**declaration):
    PwaStore("pwa", **declaration)
    return _boot_app()


def _head_of(html: str) -> str:
    return html.split("</head>")[0]


def _hrefs(head: str, rel: str) -> list[str]:
    """Every href of a ``rel`` in the head, in document order."""
    found = []
    for tag in head.split("<link ")[1:]:
        tag = tag.split(">")[0]
        if f'rel="{rel}"' in tag:
            href = tag.split('href="', 1)[1].split('"', 1)[0]
            found.append(href)
    return found


def test_a_declared_app_gets_the_manifest_and_its_icons():
    app = _app(title="Myapp")
    head = _head_of(TestClient(app).get("/demo").text)

    assert _hrefs(head, "manifest") == ["/manifest.webmanifest"]
    assert _hrefs(head, "icon") == [
        "/basis/plugins/mobile/pwa/icon-192.png",
        "/basis/plugins/mobile/pwa/icon-512.png",
    ]
    assert _hrefs(head, "apple-touch-icon") == [
        "/basis/plugins/mobile/pwa/icon-512.png"
    ]


def test_the_manifest_comes_before_the_icons():
    app = _app(title="Myapp")
    head = _head_of(TestClient(app).get("/demo").text)

    assert head.index('rel="manifest"') < head.index('rel="icon"') < head.index(
        'rel="apple-touch-icon"'
    )


def test_every_contributed_link_answers():
    """No link to a 404: each href in the head is a URL this app serves."""
    app = _app(title="Myapp")
    client = TestClient(app)
    head = _head_of(client.get("/demo").text)

    for rel in ("manifest", "icon", "apple-touch-icon"):
        for href in _hrefs(head, rel):
            response = client.get(href)
            assert response.status_code == 200, (rel, href)
            assert response.content


def test_declared_icons_are_used_in_the_head():
    app = _app(title="Myapp", icons=["/static/icon-192.png"])
    head = _head_of(TestClient(app).get("/demo").text)

    assert _hrefs(head, "icon") == ["/static/icon-192.png"]
    assert _hrefs(head, "apple-touch-icon") == ["/static/icon-192.png"]


def test_the_apple_touch_icon_defaults_to_the_largest_declared_icon():
    app = _app(
        title="Myapp",
        icons=[
            "/static/icon-192.png",
            {"src": "/static/icon-512.png", "sizes": "512x512"},
            "/static/icon-32.png",
        ],
    )
    head = _head_of(TestClient(app).get("/demo").text)

    assert _hrefs(head, "apple-touch-icon") == ["/static/icon-512.png"]


def test_an_explicit_apple_touch_icon_wins():
    app = _app(title="Myapp", apple_touch_icon="/static/touch-180.png")
    head = _head_of(TestClient(app).get("/demo").text)

    assert _hrefs(head, "apple-touch-icon") == ["/static/touch-180.png"]


def test_an_app_that_declared_nothing_contributes_no_link():
    app = _boot_app()
    head = _head_of(TestClient(app).get("/demo").text)

    for rel in ("manifest", "icon", "apple-touch-icon"):
        assert _hrefs(head, rel) == []
    assert Store._registry.get("pwa") is None


def test_a_strict_store_subset_page_still_gets_the_links():
    """The app-level guarantee, at the head: forgetting to name ``pwa`` in ``Page.stores``
    must not quietly turn installability off for one page."""
    PwaStore("pwa", title="Myapp")
    app = _boot_app(stores=["theme"])
    head = _head_of(TestClient(app).get("/demo").text)

    assert _hrefs(head, "manifest") == ["/manifest.webmanifest"]


def test_the_contribution_is_idempotent_across_requests():
    """``apply_request`` re-contributes on every render; a request must not accumulate."""
    app = _app(title="Myapp")
    client = TestClient(app)

    first = _head_of(client.get("/demo").text)
    second = _head_of(client.get("/demo").text)

    assert first.count('rel="manifest"') == 1
    assert second.count('rel="manifest"') == 1
    assert _hrefs(second, "icon") == _hrefs(first, "icon")


def test_the_links_are_in_the_serialized_state_too():
    """The client hydrates the same list, so hydration has nothing to reconcile."""
    app = _app(title="Myapp")
    html = TestClient(app).get("/demo").text
    state = json.loads(
        html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0]
    )

    assert [link["rel"] for link in state["head"]["links"]] == [
        "manifest",
        "icon",
        "icon",
        "apple-touch-icon",
    ]
    assert state["head"]["links"][0]["href"] == "/manifest.webmanifest"
