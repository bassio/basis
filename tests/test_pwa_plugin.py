"""The mobile plugin's opt-in gate.

The plugin is discovered and registered like any official plugin, but it contributes
nothing until the app declares a ``PwaStore`` — an app that never declares one must be
byte-for-byte what it was before the plugin existed. These tests are that contract, plus
the lifecycle (the serving mount, and unwinding it again).
"""
import json

import pytest
from fastapi.testclient import TestClient

from basis.plugins.mobile import PwaStore
from basis.plugins.mobile.pwa import REGISTER_URL
from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page
from basis.shared.store import Store

_DECLARATION = dict(
    title="Myapp",
    short_name="Myapp",
    icons=["/static/icon-192.png"],
)


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


def _app(declare: bool, *, stores: list | None = None):
    """A one-page app, optionally declaring a PWA the way ``stores/pwa.py`` would."""
    if declare:
        PwaStore("pwa", **_DECLARATION)
    app = Basis()
    app.bootstrap()
    # A class body cannot read a same-named enclosing local, so bind it first.
    declared_stores = list(stores or [])

    class PwaRoot(Component):
        template = "<div>hi</div>"

    class PwaDemoPage(Page):
        title = "demo"
        root_component = PwaRoot
        stores = declared_stores

    app.include_page("/demo", page_cls=PwaDemoPage)
    return app


def _initial_state_of(html: str) -> dict:
    return json.loads(
        html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0]
    )


def test_the_plugin_is_discovered_and_registered():
    app = _app(declare=False)
    assert app._plugin_registrations["mobile"].state == "enabled"
    assert app._plugin_registrations["mobile"].plugin.name == "mobile"


def test_an_app_that_declares_nothing_gets_nothing():
    app = _app(declare=False)
    html = TestClient(app).get("/demo").text

    assert "pwa" not in _initial_state_of(html)
    assert "pwa" not in Store._registry
    assert 'rel="manifest"' not in html


def test_a_declared_app_gets_the_store_in_its_initial_state():
    app = _app(declare=True)
    state = _initial_state_of(TestClient(app).get("/demo").text)

    assert state["pwa"]["title"] == "Myapp"
    assert state["pwa"]["icons"] == ["/static/icon-192.png"]
    # The worker's fields ship as neutrals, so the first client paint matches the server's.
    assert state["pwa"]["ready"] is False
    assert state["pwa"]["standalone"] is False


def test_the_declaration_also_reaches_a_strict_store_subset_page():
    """A page that lists its stores explicitly still gets ``$pwa``: the app should not
    have to remember to name its own declaration, or installability would silently stop
    working on that page alone."""
    app = _app(declare=True, stores=["theme"])
    state = _initial_state_of(TestClient(app).get("/demo").text)

    assert state["pwa"]["title"] == "Myapp"


def test_the_plugin_serves_its_package_into_the_client_vfs():
    app = _app(declare=False)

    assert any(
        getattr(route, "path", None) == "/basis/plugins/mobile"
        for route in app._component_routes
    )
    served = {path for path in app.vfs.files.values()}
    assert "./basis/plugins/mobile/store.py" in served
    assert "./basis/plugins/mobile/plugin.py" in served


def test_the_client_module_is_reachable_as_javascript():
    """The registration module is served from the plugin's package mount, not the VFS.

    The client ``import()``s it by URL, so this is the contract behind a worker ever
    getting registered: the path is the plugin's own, and the type has to be one the
    browser will execute as a module.
    """
    app = _app(declare=True)

    response = TestClient(app).get(REGISTER_URL)

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "export" in response.text


def test_disabling_the_plugin_unwinds_its_mount_and_its_store():
    import asyncio

    app = _app(declare=True)
    assert "pwa" in Store._registry

    assert asyncio.run(app.remove_plugin("mobile")) is True

    assert not any(
        getattr(route, "path", None) == "/basis/plugins/mobile"
        for route in app._component_routes
    )
    served = {path for path in app.vfs.files.values()}
    assert "./basis/plugins/mobile/store.py" not in served
    # The registration is disposed, so nothing re-wires the store on the next render.
    assert app._plugin_registrations["mobile"].disposed is True
