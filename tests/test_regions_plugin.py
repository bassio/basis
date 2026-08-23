"""
Regions-as-an-official-plugin tests (REGIONS-PLUGIN-PLAN.md Phase 2).

Covers the ``basis.plugins`` entry-point registration (the regions plugin is
discovered and auto-registered at bootstrap exactly like a third-party plugin),
and the first-class plugin store-inclusion API (``@plugin.store`` /
``BasisPlugin.include_store``) that wires a plugin-provided store into the app
(construct/blueprint, ``_requires_app`` attach, app-global store list) and
unwinds it on remove.
"""
import asyncio
import json
import re

import pytest
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.server.plugin import BasisPlugin
from basis.shared.component import Component
from basis.shared.page import _synthesize_page
from basis.shared.store import Store

from basis.plugins.regions.plugin import RegionsPlugin
from basis.plugins.regions.store import RegionStore


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


# ---------------------------------------------------------------------------
# Entry-point registration (D1).
# ---------------------------------------------------------------------------

def test_regions_plugin_discoverable_via_entry_point():
    from basis.server.plugins import discover_installed_plugins

    plugins = discover_installed_plugins()
    regions = next((p for p in plugins if p.name == "regions"), None)
    assert regions is not None, "regions entry point not discovered"
    assert isinstance(regions, RegionsPlugin)
    assert regions.static_mount == "/basis/plugins/regions"


def test_bootstrap_registers_regions_plugin_and_wires_store():
    app = Basis()
    app.bootstrap()

    reg = app._plugin_registrations.get("regions")
    assert reg is not None
    assert reg.plugin.name == "regions"
    # $regions is an app-bound store (_requires_app projection of app._regions).
    assert RegionStore._requires_app is True
    # on_register created the app-owned store + app-global store list entry.
    assert hasattr(app, "regions")
    assert app.regions.get_store_name() == "regions"
    assert app.regions._app is app
    assert any(c["name"] == "regions" for c in app._global_stores)
    assert Store._registry.get("regions") is not None
    # Recorded on the registration via the first-class store API (revertible).
    assert ("regions", RegionStore) in reg.store_items


def test_regions_plugin_is_framework_essential_non_disableable():
    """The regions plugin is framework-essential (it provides <ui-region> /
    $regions that a page depends on): disable/remove are refused, so the plugin
    manager cannot strand an app that hosts a region."""
    app = Basis()
    app.bootstrap()
    assert "regions" in app._plugin_registrations

    # Refused even though no app component imports the plugin modules.
    assert asyncio.run(app.disable_plugin("regions")) is False
    assert asyncio.run(app.remove_plugin("regions")) is False
    assert app._plugin_registrations["regions"].disposed is False

    # force=True still allows a deliberate unload.
    assert asyncio.run(app.remove_plugin("regions", force=True)) is True
    assert app._plugin_registrations["regions"].disposed is True


def test_regions_plugin_static_mount_is_isomorphic(caplog):
    app = Basis()
    app.bootstrap()
    client = TestClient(app)
    # The plugin's static dir is served at /basis/plugins/regions and the
    # isomorphism guard (static_mount == package path) did not warn.
    resp = client.get("/basis/plugins/regions/plugin.py")
    assert resp.status_code == 200
    assert "isomorphism" not in caplog.text.lower()


# ---------------------------------------------------------------------------
# $regions serialization (SSR + CSR default-all).
# ---------------------------------------------------------------------------

def test_regions_serialized_into_ssr_initial_state():
    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div class="app-root"><ui-region name="statusbar-right"></ui-region></div>"""

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200

    html = resp.text
    state = json.loads(
        html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0]
    )
    assert "regions" in state


def test_regions_serialized_into_csr_initial_state_default_all():
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

    match = re.search(
        r'<script id="basis-initial-state"[^>]*>(.*?)</script>',
        resp.text,
        re.DOTALL,
    )
    assert match, "basis-initial-state script not found"
    state = json.loads(match.group(1))
    # Default-all page: $regions is a live/blueprinted store (the plugin
    # registered it at boot) so it is serialized.
    assert "regions" in state


# ---------------------------------------------------------------------------
# First-class plugin store-inclusion API.
# ---------------------------------------------------------------------------

class _AppBoundStore(Store):
    _requires_app = True

    def __init__(self, name="appbound"):
        super().__init__(name)
        if not getattr(self, "_hydrated_from_ssr", False):
            self.__dict__["items"] = {}

    def _refresh_from_app(self):
        self.__dict__["items"] = {"v": 1}


def test_plugin_store_decorator_wires_store_into_app():
    app = Basis()
    app.bootstrap()
    plugin = BasisPlugin(prefix="/p", name="p")

    @plugin.store("pstore")
    class PStore(_AppBoundStore):
        pass

    reg = app.include_plugin(plugin)
    assert reg.store_items == [("pstore", PStore)]

    store = Store._registry.get("pstore")
    assert store is not None
    assert store._app is app          # _requires_app → app-attached
    assert store.items == {"v": 1}    # projection refreshed
    assert any(c["name"] == "pstore" for c in app._global_stores)

    # Unwind on remove.
    asyncio.run(app.remove_plugin("p"))
    assert not any(c["name"] == "pstore" for c in app._global_stores)
    assert Store._registry.get("pstore") is None


def test_plugin_include_store_method_wires_directly():
    app = Basis()
    app.bootstrap()
    plugin = BasisPlugin(prefix="/q", name="q")

    store = plugin.include_store(app, _AppBoundStore, "qstore")
    assert Store._registry.get("qstore") is store
    assert store._app is app
    assert store.items == {"v": 1}
    assert any(c["name"] == "qstore" for c in app._global_stores)
    # The method form also records for revertibility.
    assert ("qstore", _AppBoundStore) in plugin._store_items


def test_plugin_include_store_default_name_uses_store_default():
    app = Basis()
    app.bootstrap()
    plugin = BasisPlugin(prefix="/r", name="r")

    store = plugin.include_store(app, _AppBoundStore)  # name=None → "appbound"
    assert store.get_store_name() == "appbound"
    assert Store._registry.get("appbound") is store


def test_client_plugin_shim_has_store_api():
    from basis.client.plugin import BasisPlugin as ClientPlugin

    p = ClientPlugin(prefix="/c", name="c")

    @p.store
    class CStore:
        pass

    assert p._store_items == [(None, CStore)]
    assert callable(p.include_store)


# ---------------------------------------------------------------------------
# Region hydration wiring (on_hydrated / SSR-path flag / idempotent subscribe).
# ---------------------------------------------------------------------------

def test_region_subscribe_to_store_is_idempotent():
    """``Region._subscribe_to_region_store`` must not double-register: a single
    subscription and a single ``region_sync`` DAG effect, even when called from
    both the (deferred) ``on_mounted`` and ``on_hydrated`` paths. The DAG
    ``add_effect`` does not dedupe by name, so the guard matters."""
    from basis.plugins.regions.region import Region
    from basis.plugins.regions.store import RegionStore

    store = RegionStore("regions")  # self-registers in Store._registry
    region = Region()

    region._subscribe_to_region_store()
    region._subscribe_to_region_store()

    assert len(store._subscriptions) == 1
    n_effects = sum(1 for e in region._dag.effects if e.name == "region_sync")
    assert n_effects == 1


def test_ssr_hydration_flag_defaults_false_and_round_trips():
    """The ``mount_app_ssr`` flag (``in_ssr_hydration``) is False by default
    (server render + CSR) and set/reset around SSR hydration — it is the
    reliable signal ``<ui-region>`` uses to defer contribution mounting to
    ``on_hydrated``."""
    from basis.shared.component import _set_ssr_hydration, in_ssr_hydration

    _set_ssr_hydration(False)
    assert in_ssr_hydration() is False
    _set_ssr_hydration(True)
    assert in_ssr_hydration() is True
    _set_ssr_hydration(False)
    assert in_ssr_hydration() is False


# ---------------------------------------------------------------------------
# $regions live re-sync after a plugin disable/enable.
#
# Local to the regions plugin, on top of generic framework primitives:
#   * ``AppStateStore.refresh`` — the generic app-bound re-sync RPC (pull the
#     current listing for any ``_requires_app`` store).
#   * ``Store.add_subscription`` — the cross-object DAG edge (the mechanism
#     ``ComponentSubscription`` became): ``RegionStore.__init__`` calls
#     ``$plugins.add_subscription(self, "items")``, so whenever ``$plugins``
#     updates on the client (e.g. after a disable/enable) the edge triggers
#     ``$regions.react(["$plugins.items"])`` → a server re-pull. No framework
#     code knows "regions" by name.
# ---------------------------------------------------------------------------

def test_region_store_uses_generic_refresh_action_after_plugin_disable():
    """``$regions`` re-syncs through the generic ``refresh`` RPC (inherited from
    ``AppStateStore`` — the same primitive any ``_requires_app`` store uses):
    it returns the authoritative listing re-read from the app, so a client can
    pull the current region state on demand — e.g. after a plugin disable/enable
    unwinds/restores contributions."""
    import asyncio

    from basis.server.plugin import BasisPlugin

    app = Basis()
    app.bootstrap()

    plugin = BasisPlugin(prefix="/demo", name="demo")

    @plugin.region("activity")
    class DemoIcon(Component):
        def template(self):
            return "<div class='demo-icon'>icon</div>"

    app.include_plugin(plugin)

    client = TestClient(app)

    def refresh_listing():
        resp = client.post(
            "/basis/api/action",
            json={
                "path": "basis.shared.app_state.AppStateStore.refresh",
                "store_name": "regions",
                "args": [],
                "kwargs": {},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["ok"] is True
        # new_state is the authoritative listing (applied to the client
        # $regions store by the RPC layer).
        return body["new_state"]["items"]

    listing = refresh_listing()
    assert [e["cls_path"].rsplit(".", 1)[-1] for e in listing["activity"]] == ["DemoIcon"]

    # Disable the contributing plugin → its contribution is unwound server-side
    # and the next refresh no longer lists it.
    assert asyncio.run(app.disable_plugin("demo")) is True
    listing = refresh_listing()
    assert listing.get("activity") in (None, [])

    # Re-enable → contribution restored.
    assert asyncio.run(app.enable_plugin("demo")) is True
    listing = refresh_listing()
    assert [e["cls_path"].rsplit(".", 1)[-1] for e in listing["activity"]] == ["DemoIcon"]


def test_region_store_subscribes_to_plugins_via_dag_edge():
    """``RegionStore`` subscribes to ``$plugins.items`` through a first-class
    cross-object DAG edge (the mechanism ``ComponentSubscription`` became —
    BINDINGS-REVIEW §6): ``$plugins.add_subscription(self, "items")`` registers
    an effect on ``$plugins``' graph keyed on ``items``. No framework code knows
    "regions" by name."""
    from basis.plugins.regions.store import RegionStore
    from basis.shared.plugin_registry import PluginRegistryStore

    plugins = PluginRegistryStore("plugins")
    regions = RegionStore("regions")
    try:
        # target-side edge: $plugins tracked the subscription + wired a DAG effect
        assert (regions, "items") in plugins._subscriptions
        effect = plugins._dag.nodes.get(f"sub_{id(regions)}_items")
        assert effect is not None
        assert "items" in {d.name for d in effect.dependencies}
    finally:
        for name in ("plugins", "regions"):
            Store._store_blueprints.pop(name, None)
            Store._registry.pop(name, None)


def test_region_store_resyncs_when_plugins_items_change():
    """A client-side ``$plugins.items`` change fires the DAG edge → ``$regions``
    ``react([...])`` translates it into a server re-pull."""
    from basis.plugins.regions.store import RegionStore
    from basis.shared.plugin_registry import PluginRegistryStore

    plugins = PluginRegistryStore("plugins")
    regions = RegionStore("regions")
    try:
        resynced = []
        regions._resync_from_plugins = lambda: resynced.append(True)

        # a client-side $plugins update (e.g. new_state applied via update())
        plugins.items = {"svc": {"state": "enabled"}}

        assert resynced == [True]
    finally:
        for name in ("plugins", "regions"):
            Store._store_blueprints.pop(name, None)
            Store._registry.pop(name, None)
