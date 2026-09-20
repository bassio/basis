"""``$head.links`` — the head ``<link>`` channel.

A plugin or component that owns head content the page cannot author contributes ``<link>``
items to ``$head``; the base template renders them through a keyed head loop, so
whole-page hydration keeps the loop alive (the same mechanism ``theme-color`` rides
through ``$head.metas``).

These tests cover the channel itself, through the real render path with a stand-in
contributor: the item shape, the optional-attribute omission, the loop's reconciliation
key, and the serialized state the client hydrates. The PWA contributions built on it
(manifest, icons) land with the mobile plugin.
"""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

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


class LinkContributor(Store):
    """Stands in for a plugin that owns head links (the mobile plugin's role).

    ``apply_request`` is the per-request seam: ``Store._registry`` is cleared between
    requests, so anything contributed once at boot would not survive into a render.
    """

    def apply_request(self, request) -> None:
        head = Store._registry.get("head")
        if head is None:
            return
        head.add_link("manifest", "/manifest.webmanifest")
        head.add_link("icon", "/icon-192.png", type="image/png", sizes="192x192")
        head.add_link("apple-touch-icon", "/icon-192.png")


def _page(contributor: bool = True):
    app = Basis()
    app.bootstrap()
    if contributor:
        LinkContributor("links")
        app.include_store("links")

    class Root(Component):
        template = "<div>hi</div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    return app, DemoPage


def _head_of(html: str) -> str:
    return html.split("</head>")[0]


def _initial_state_of(html: str) -> dict:
    return json.loads(
        html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0]
    )


def test_contributed_links_render_in_the_head_in_order():
    app, _ = _page()
    head = _head_of(TestClient(app).get("/demo").text)

    manifest = head.index('rel="manifest"')
    icon = head.index('rel="icon"')
    apple = head.index('rel="apple-touch-icon"')
    assert manifest < icon < apple


def test_a_link_carries_its_optional_attributes():
    app, _ = _page()
    head = _head_of(TestClient(app).get("/demo").text)

    assert '<link rel="icon" href="/icon-192.png" type="image/png" sizes="192x192"' in head


def test_an_absent_attribute_is_omitted_not_written_as_none():
    """The manifest link declares no ``sizes``/``type``: the loop's bindings are fixed,
    so an unset attribute has to disappear rather than render a sentinel."""
    app, _ = _page()
    head = _head_of(TestClient(app).get("/demo").text)

    manifest_tag = next(
        part.split(">")[0]
        for part in head.split("<link ")[1:]
        if 'rel="manifest"' in part
    )
    assert "sizes" not in manifest_tag
    assert "type" not in manifest_tag
    assert "None" not in manifest_tag


def test_the_loop_stamps_the_reconciliation_key_and_a_hydration_id():
    app, _ = _page()
    head = _head_of(TestClient(app).get("/demo").text)

    assert 'data-item-key="manifest:/manifest.webmanifest"' in head
    manifest_tag = next(
        part.split(">")[0]
        for part in head.split("<link ")[1:]
        if 'rel="manifest"' in part
    )
    assert "data-hydration-id" in manifest_tag


def test_links_serialize_into_the_initial_state_in_the_loop_shape():
    app, _ = _page()
    state = _initial_state_of(TestClient(app).get("/demo").text)

    assert state["head"]["links"] == [
        {
            "key": "manifest:/manifest.webmanifest",
            "rel": "manifest",
            "href": "/manifest.webmanifest",
            "type": None,
            "sizes": None,
            "as": None,
            "media": None,
            "crossorigin": None,
        },
        {
            "key": "icon:/icon-192.png",
            "rel": "icon",
            "href": "/icon-192.png",
            "type": "image/png",
            "sizes": "192x192",
            "as": None,
            "media": None,
            "crossorigin": None,
        },
        {
            "key": "apple-touch-icon:/icon-192.png",
            "rel": "apple-touch-icon",
            "href": "/icon-192.png",
            "type": None,
            "sizes": None,
            "as": None,
            "media": None,
            "crossorigin": None,
        },
    ]


def test_no_contributor_renders_no_contributed_link():
    app, _ = _page(contributor=False)
    html = TestClient(app).get("/demo").text

    head = _head_of(html)
    assert 'rel="manifest"' not in head
    assert 'rel="icon"' not in head

    state = _initial_state_of(html)
    assert state["head"]["links"] == []
    # The metas list is a separate channel: the theme's theme-color is still there,
    # and the empty link list renders nothing (byte-stable head).
    assert [m["name"] for m in state["head"]["metas"]] == ["theme-color"]


def test_csr_initial_state_carries_the_links():
    import asyncio

    from basis.server.render import render_page

    app, page_cls = _page()
    html = asyncio.run(
        render_page(SimpleNamespace(app=app, cookies={}), page_cls, render_mode="csr")
    )

    assert 'rel="manifest" href="/manifest.webmanifest"' in _head_of(html)
    assert _initial_state_of(html)["head"]["links"][0]["key"] == (
        "manifest:/manifest.webmanifest"
    )
