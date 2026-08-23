"""
Plugin lifecycle tests: name validation, ``requires`` dependency ordering, the
revertible registration layer (``remove_plugin`` / ``disable_plugin`` /
``enable_plugin``), and the ``$plugins`` PluginRegistryStore control plane.

Covers the Cordis-inspired "live plugin lifecycle" work in
``ROADMAP-EXTENSIBILITY.md``.
"""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis, _topo_sort_plugins
from basis.server.plugin import BasisPlugin
from basis.shared.store import Store


# ---------------------------------------------------------------------------
# Isolation: class-level app state is shared across Basis instances.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_plugin_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes
    Store._registry.clear()
    Store._store_blueprints.clear()


class ShutdownTrap(BasisPlugin):
    """Records on_shutdown calls to prove teardown runs exactly once."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.shutdown_calls = 0

    async def on_shutdown(self, app):
        self.shutdown_calls += 1


# ---------------------------------------------------------------------------
# Plugin names must be valid Python identifiers.
# ---------------------------------------------------------------------------

def test_plugin_name_explicit_invalid_raises():
    with pytest.raises(ValueError, match="valid Python identifier"):
        BasisPlugin(prefix="/chat", name="my chat plugin")
    with pytest.raises(ValueError, match="valid Python identifier"):
        BasisPlugin(prefix="/chat", name="my-plugin")
    with pytest.raises(ValueError, match="valid Python identifier"):
        BasisPlugin(prefix="/chat", name="class")  # Python keyword


def test_plugin_name_explicit_valid_ok():
    assert BasisPlugin(prefix="/chat", name="chat").name == "chat"
    assert BasisPlugin(prefix="/a-b", name="a_b").name == "a_b"


def test_plugin_name_derived_default_is_sanitized():
    assert BasisPlugin(prefix="/my-plugin").name == "my_plugin"
    assert BasisPlugin(prefix="/chat").name == "chat"
    assert BasisPlugin(prefix="/123abc").name == "_123abc"


def test_client_shim_applies_same_name_rule():
    from basis.client.plugin import BasisPlugin as ClientBasisPlugin
    with pytest.raises(ValueError, match="valid Python identifier"):
        ClientBasisPlugin(prefix="/chat", name="bad name")
    assert ClientBasisPlugin(prefix="/my-plugin").name == "my_plugin"


def test_client_shim_exposes_plugin_actions_as_callable_attributes():
    """P5: the client shim exposes ``@plugin.action`` methods as attributes so the
    direct-import invocation form (``await plugin.<action>()``) works without a
    proxy object."""
    from basis.client.plugin import BasisPlugin as ClientBasisPlugin

    p = ClientBasisPlugin(prefix="/x", name="x")

    @p.action
    def ping():
        return "pong"

    assert hasattr(p, "ping")


# ---------------------------------------------------------------------------
# requires: dependency ordering + fail-loud missing dep + cycle detection.
# ---------------------------------------------------------------------------

def test_include_plugin_requires_missing_dep_fails_loud():
    app = Basis()
    app.bootstrap()
    child = BasisPlugin(prefix="/child", name="child", requires=["base"])
    with pytest.raises(ValueError, match="requires \\['base'\\]"):
        app.include_plugin(child)


def test_include_plugin_requires_ok_when_dep_registered_first():
    app = Basis()
    app.bootstrap()
    dep = BasisPlugin(prefix="/base", name="base")
    child = BasisPlugin(prefix="/child", name="child", requires=["base"])
    app.include_plugin(dep)
    reg = app.include_plugin(child)
    assert reg.plugin is child
    assert child.name in app._plugin_registrations


def test_topo_sort_orders_dependencies_first():
    a = BasisPlugin(prefix="/a", name="a")
    b = BasisPlugin(prefix="/b", name="b", requires=["a"])
    c = BasisPlugin(prefix="/c", name="c", requires=["b"])
    assert [p.name for p in _topo_sort_plugins([c, a, b])] == ["a", "b", "c"]


def test_topo_sort_missing_dep_and_cycle_raise():
    with pytest.raises(ValueError, match="missing required plugin"):
        _topo_sort_plugins([BasisPlugin(prefix="/x", name="x", requires=["nope"])])
    d = BasisPlugin(prefix="/d", name="d", requires=["e"])
    e = BasisPlugin(prefix="/e", name="e", requires=["d"])
    with pytest.raises(ValueError, match="cycle"):
        _topo_sort_plugins([d, e])


# ---------------------------------------------------------------------------
# Revertible registration: include → remove → re-enable.
# ---------------------------------------------------------------------------

def _make_plugin():
    plugin = ShutdownTrap(prefix="/svc", name="svc")

    @plugin.get("/ping")
    async def ping():
        return {"pong": True}

    @plugin.action
    async def do_thing(x: int):
        return {"x": x}

    return plugin


def test_remove_plugin_unwinds_routes_actions_and_registry():
    app = Basis()
    app.bootstrap()
    plugin = _make_plugin()

    reg = app.include_plugin(plugin)
    assert reg is app._plugin_registrations["svc"]
    assert len(reg.added_routes) == 1  # the /svc/ping route
    do_thing_path = f"{plugin.actions['do_thing'].__module__}.{plugin.actions['do_thing'].__qualname__}"

    client = TestClient(app)
    assert client.get("/svc/ping").status_code == 200
    r = client.post("/basis/api/action", json={
        "path": do_thing_path, "action_name": "do_thing", "plugin_name": "svc",
        "args": [1], "kwargs": {},
    })
    assert r.status_code == 200 and r.json()["data"] == {"x": 1}
    registry = client.get("/basis/api/plugins").json()
    assert "svc" in registry and "do_thing" in registry["svc"]["actions"]

    # --- remove ---
    assert asyncio.run(app.remove_plugin("svc")) is True
    assert plugin.shutdown_calls == 1
    assert all(p.name != "svc" for p in app._plugins)
    assert app._plugin_registrations["svc"].disposed is True
    assert client.get("/svc/ping").status_code == 404
    r = client.post("/basis/api/action", json={
        "path": do_thing_path, "action_name": "do_thing", "plugin_name": "svc",
        "args": [], "kwargs": {},
    })
    assert r.status_code == 404
    # The listing intentionally keeps disabled plugins (so a manager can offer
    # re-enable); the route/action are gone (asserted above).
    assert client.get("/basis/api/plugins").json()["svc"]["state"] == "disabled"

    # double-remove is a no-op
    assert asyncio.run(app.remove_plugin("svc")) is False
    assert plugin.shutdown_calls == 1  # on_shutdown ran exactly once

    # --- re-enable restores everything ---
    assert asyncio.run(app.enable_plugin("svc")) is True
    assert client.get("/svc/ping").status_code == 200
    r = client.post("/basis/api/action", json={
        "path": do_thing_path, "action_name": "do_thing", "plugin_name": "svc",
        "args": [2], "kwargs": {},
    })
    assert r.status_code == 200 and r.json()["data"] == {"x": 2}


def test_disable_plugin_alias_and_enable_missing_returns_false():
    app = Basis()
    app.bootstrap()
    plugin = _make_plugin()
    app.include_plugin(plugin)

    assert asyncio.run(app.disable_plugin("svc")) is True
    assert all(p.name != "svc" for p in app._plugins)
    # enabling an unknown / never-disabled plugin is a no-op
    assert asyncio.run(app.enable_plugin("nope")) is False
    assert asyncio.run(app.enable_plugin("svc")) is True
    assert any(p.name == "svc" for p in app._plugins)


def test_remove_plugin_unmounts_static_dir_and_prunes_vfs(tmp_path):
    app = Basis()
    app.bootstrap()
    comp_dir = tmp_path / "components"
    comp_dir.mkdir()
    (comp_dir / "gadget.py").write_text("class Gadget:\n    pass\n")
    plugin = BasisPlugin(
        prefix="/gadget", name="gadget",
        static_dir=comp_dir, static_mount="/gadget",
    )
    reg = app.include_plugin(plugin)
    assert reg.component_mount is not None
    assert any(getattr(r, "path", None) == "/gadget" for r in app._component_routes)
    assert any(getattr(r, "path", None) == "/gadget" for r in app.routes)

    asyncio.run(app.remove_plugin("gadget"))

    assert all(getattr(r, "path", None) != "/gadget" for r in app._component_routes)
    assert all(getattr(r, "path", None) != "/gadget" for r in app.routes)
    # The PyScript VFS manifest no longer advertises the plugin's files.
    vfs = app.vfs.files
    assert not any("gadget" in str(v) for v in vfs.values())


def test_disable_enable_cycle_restores_vfs_manifest(tmp_path):
    """A disable→enable cycle must restore the plugin's VFS entries.

    ``remove_plugin`` (the disable path) surgically prunes the plugin's files
    from the PyScript VFS manifest; ``enable_plugin`` re-mounts the static dir,
    restoring them. Without that, the client can no longer import the plugin's
    modules on the next page load — the SSR app renders but never hydrates
    (broken events), because mounting is gated on importing the page component.
    """
    app = Basis()
    app.bootstrap()
    comp_dir = tmp_path / "components"
    comp_dir.mkdir()
    (comp_dir / "gadget.py").write_text("class Gadget:\n    pass\n")
    plugin = BasisPlugin(
        prefix="/gadget", name="gadget",
        static_dir=comp_dir, static_mount="/gadget",
    )
    app.include_plugin(plugin)
    # The app's live VFS registry already includes the plugin's files.
    assert any("gadget" in str(v) for v in app.vfs.files.values())

    asyncio.run(app.disable_plugin("gadget"))
    # remove_plugin surgically pruned the plugin's files from the manifest.
    assert not any("gadget" in str(v) for v in app.vfs.files.values())

    asyncio.run(app.enable_plugin("gadget"))
    # enable_plugin re-mounts the static dir, restoring its manifest entries.
    assert any(getattr(r, "path", None) == "/gadget" for r in app._component_routes)
    assert any("gadget" in str(v) for v in app.vfs.files.values())


def test_remove_plugin_refuses_when_imported_by_consumer(tmp_path):
    """A plugin a client module imports directly is essential — disable/remove
    refuses (returns False) unless force=True.

    Mirrors the Jotter case: the page component imports ``jotter.plugins``, so
    disabling that plugin would prune it from the client VFS and break the next
    page load (render but never hydrate).
    """
    app = Basis()
    app.bootstrap()

    # Plugin owns a real package dir, so its canonical package resolves
    # ("myapp.plugins" — every level carries an ``__init__.py``).
    app_pkg = tmp_path / "myapp"
    app_pkg.mkdir(parents=True)
    (app_pkg / "__init__.py").write_text("")
    pkg_dir = app_pkg / "plugins"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "widget.py").write_text("class Widget:\n    pass\n")
    plugin = BasisPlugin(
        prefix="/myapp/plugins", name="widget",
        static_dir=pkg_dir, static_mount="/myapp/plugins",
    )

    # Consumer component (sibling package) imports the plugin directly.
    comp_dir = app_pkg / "components"
    comp_dir.mkdir()
    (comp_dir / "__init__.py").write_text("")
    (comp_dir / "app.py").write_text("from myapp.plugins.widget import Widget\n")

    app.include_components_dir("/myapp/components", str(comp_dir), name="app")
    app.include_plugin(plugin)

    # Directly imported → pinned → refused without force.
    assert asyncio.run(app.remove_plugin("widget")) is False
    assert asyncio.run(app.disable_plugin("widget")) is False
    # The refusal left the registration intact (still enabled).
    assert app._plugin_registrations["widget"].disposed is False

    # force=True overrides the guard and unloads.
    assert asyncio.run(app.remove_plugin("widget", force=True)) is True
    assert app._plugin_registrations["widget"].disposed is True


def test_plugin_importers_cached_and_invalidated_on_mutations(tmp_path):
    """The plugin→importers map is computed once, cached, then dropped on any
    structural change (a component-dir mount or a plugin remove), so the next
    call recomputes from the current mounts."""
    app = Basis()
    app.bootstrap()

    app_pkg = tmp_path / "myapp"
    app_pkg.mkdir(parents=True)
    (app_pkg / "__init__.py").write_text("")
    pkg_dir = app_pkg / "plugins"
    pkg_dir.mkdir()
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "widget.py").write_text("class Widget:\n    pass\n")
    plugin = BasisPlugin(
        prefix="/myapp/plugins", name="widget",
        static_dir=pkg_dir, static_mount="/myapp/plugins",
    )

    comp_dir = app_pkg / "components"
    comp_dir.mkdir()
    (comp_dir / "__init__.py").write_text("")
    (comp_dir / "app.py").write_text("from myapp.plugins.widget import Widget\n")
    app.include_components_dir("/myapp/components", str(comp_dir), name="app")
    app.include_plugin(plugin)

    first = app._plugin_importers()
    assert first == {"widget": ["myapp.components.app"]}
    # Cached: the second call is the same object, not recomputed.
    assert app._plugin_importers() is first

    # Mounting another consumer dir invalidates the cache and widens the pin.
    extra = app_pkg / "extra"
    extra.mkdir()
    (extra / "x.py").write_text("from myapp.plugins.widget import Widget\n")
    app.include_components_dir("/myapp/extra", str(extra), name="extra")
    assert app._plugin_importers_cache is None
    assert app._plugin_importers() == {
        "widget": ["myapp.components.app", "myapp.extra.x"],
    }

    # Removing the plugin invalidates again; a disposed plugin is not tracked.
    assert asyncio.run(app.remove_plugin("widget", force=True)) is True
    assert app._plugin_importers_cache is None
    assert app._plugin_importers() == {}


def test_include_plugin_idempotent_returns_existing_registration():
    app = Basis()
    app.bootstrap()
    plugin = _make_plugin()
    first = app.include_plugin(plugin)
    second = app.include_plugin(plugin)
    assert second is first
    # Idempotent — the same plugin instance is never added twice. (Bootstrap
    # auto-registers the official regions plugin, so _plugins has more than
    # just this one; count-by-identity is the robust assertion.)
    assert app._plugins.count(plugin) == 1


# ---------------------------------------------------------------------------
# PluginRegistryStore control plane ($plugins).
# ---------------------------------------------------------------------------

def test_registry_store_is_wired_and_projects_registrations():
    app = Basis()
    app.bootstrap()
    assert hasattr(app, "plugins")
    assert app.plugins.get_store_name() == "plugins"

    plugin = BasisPlugin(prefix="/chat", name="chat")

    @plugin.action
    async def hi():
        return "hi"

    app.include_plugin(plugin)
    snap = app.plugins.serialize()
    assert snap["items"]["chat"]["state"] == "enabled"
    assert "hi" in snap["items"]["chat"]["actions"]
    assert snap["items"]["chat"]["prefix"] == "/chat"


def test_disable_enable_via_store_bound_action_over_http():
    app = Basis()
    app.bootstrap()
    plugin = _make_plugin()
    app.include_plugin(plugin)
    client = TestClient(app)

    path = "basis.shared.plugin_registry.PluginRegistryStore.disable"
    r = client.post("/basis/api/action", json={
        "path": path, "store_name": "plugins", "args": ["svc"], "kwargs": {},
    })
    assert r.status_code == 200
    data = r.json()
    assert data["data"] == {"ok": True}
    # Disabled plugins stay visible in the projection with state='disabled' so a
    # manager panel can offer re-enable; the route itself is gone.
    assert data["new_state"]["items"]["svc"]["state"] == "disabled"
    assert client.get("/svc/ping").status_code == 404

    path = "basis.shared.plugin_registry.PluginRegistryStore.enable"
    r = client.post("/basis/api/action", json={
        "path": path, "store_name": "plugins", "args": ["svc"], "kwargs": {},
    })
    assert r.status_code == 200
    assert r.json()["data"] == {"ok": True}
    assert client.get("/svc/ping").status_code == 200


def test_registry_store_refresh_server_action_returns_projection():
    """CSR bootstrap: the client pulls $plugins.items via the refresh action.

    The server re-attaches the app, recomputes the projection and returns it in
    ``new_state`` (which the client store applies) — the client-side equivalent
    of SSR hydration. Disabled plugins stay visible so they can be re-enabled.
    """
    app = Basis()
    app.bootstrap()
    plugin = _make_plugin()
    app.include_plugin(plugin)
    client = TestClient(app)

    path = "basis.shared.app_state.AppStateStore.refresh"
    r = client.post("/basis/api/action", json={
        "path": path, "store_name": "plugins", "args": [], "kwargs": {},
    })
    assert r.status_code == 200
    payload = r.json()
    assert payload["data"]["ok"] is True
    items = payload["new_state"]["items"]
    assert "svc" in items
    assert items["svc"]["state"] == "enabled"
    assert "do_thing" in items["svc"]["actions"]
    assert items["svc"]["prefix"] == "/svc"

    # A disabled plugin is still projected (state='disabled') so the panel can
    # offer re-enable — the same shape SSR hydration carries.
    assert asyncio.run(app.disable_plugin("svc")) is True
    r = client.post("/basis/api/action", json={
        "path": path, "store_name": "plugins", "args": [], "kwargs": {},
    })
    assert r.status_code == 200
    assert r.json()["new_state"]["items"]["svc"]["state"] == "disabled"


def test_plugins_projection_endpoint_includes_disabled_plugins():
    """CSR bootstrap pulls $plugins.items from GET /basis/api/plugins.

    The listing endpoint carries state/prefix/requires and includes disabled
    plugins (so a panel can offer re-enable) — the exact shape SSR hydration
    serializes.
    """
    app = Basis()
    app.bootstrap()
    app.include_plugin(_make_plugin())
    client = TestClient(app)

    registry = client.get("/basis/api/plugins").json()
    # The official regions plugin is auto-registered by bootstrap, so assert the
    # svc entry exactly rather than the whole listing.
    assert registry["svc"] == {
        "state": "enabled",
        "prefix": "/svc",
        "actions": ["do_thing"],
        "requires": [],
    }
    assert registry["regions"]["state"] == "enabled"

    asyncio.run(app.disable_plugin("svc"))
    registry = client.get("/basis/api/plugins").json()
    assert registry["svc"]["state"] == "disabled"
    assert "do_thing" in registry["svc"]["actions"]


def test_csr_page_initial_state_serializes_plugin_registry_projection():
    """CSR pages (render_full_page with no initial_state_json) must embed the
    plugins projection in #basis-initial-state — the client hydrates $plugins
    from it.

    Regression: _prepare_full_page called Store.resolve('plugins') (a fresh
    instance with no owning app), so serialize() projected empty items and the
    CSR view showed "0 plugins" while SSR was fine.
    """
    from types import SimpleNamespace
    from basis.shared.component import Component
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()
    app.include_plugin(_make_plugin())

    class Root(Component):
        template = "<div>csr</div>"

    class CsrPage(Page):
        title = "csr"
        root_component = Root

    page_instance = CsrPage.load()
    html = page_instance.render_full_page(request=SimpleNamespace(app=app))
    assert 'id="basis-initial-state"' in html
    state = json.loads(
        html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0]
    )
    assert "plugins" in state
    assert state["plugins"]["items"]["svc"]["state"] == "enabled"
    assert "do_thing" in state["plugins"]["items"]["svc"]["actions"]


def test_plugin_listing_is_single_source_for_store_and_endpoint():
    """P1: ``_plugin_listing(app)`` is the one listing builder — the ``$plugins``
    store refresh and ``GET /basis/api/plugins`` must produce identical output."""
    from basis.shared.plugin_registry import _plugin_listing

    app = Basis()
    app.bootstrap()
    app.include_plugin(_make_plugin())
    client = TestClient(app)

    listing = _plugin_listing(app)
    assert listing == client.get("/basis/api/plugins").json()
    app.plugins._refresh_from_app()
    assert listing == app.plugins.__dict__["items"]
    assert listing["svc"]["state"] == "enabled"

    asyncio.run(app.disable_plugin("svc"))
    listing = _plugin_listing(app)
    assert listing["svc"]["state"] == "disabled"
    assert listing == client.get("/basis/api/plugins").json()


def test_get_all_stores_attaches_app_to_app_bound_store():
    from basis.server.ssr import _get_all_stores
    from basis.shared.plugin_registry import PluginRegistryStore

    app = Basis()
    app.bootstrap()
    Store._registry.clear()

    store = _get_all_stores(
        type("P", (), {}), type("R", (), {}),
        global_stores=[{"name": "plugins"}], request_app=app,
    )["plugins"]
    assert isinstance(store, PluginRegistryStore)
    assert store.__dict__.get("_app") is app

    plugin = BasisPlugin(prefix="/chat", name="chat")
    app.include_plugin(plugin)
    assert "chat" in store.serialize()["items"]


def test_plugin_action_handler_attaches_app_to_app_bound_store():
    """P3 regression: a store-bound ``@plugin.action`` on an app-bound store
    (``_requires_app``) must get the app attached — the RPC handler attaches
    app-bound stores before running the action."""
    from basis.shared.store import Store

    class AppBoundStore(Store):
        _requires_app = True

    app = Basis()
    app.bootstrap()
    AppBoundStore("app_bound")

    plugin = BasisPlugin(prefix="/gap", name="gap")

    @plugin.action
    async def ping_plugin(_store):
        return {"has_app": getattr(_store, "_app", None) is not None}

    app.include_plugin(plugin)
    client = TestClient(app)

    r = client.post("/basis/api/action", json={
        "path": f"{plugin.actions['ping_plugin'].__module__}.{plugin.actions['ping_plugin'].__qualname__}",
        "action_name": "ping_plugin", "plugin_name": "gap",
        "store_name": "app_bound", "args": [], "kwargs": {},
    })
    assert r.status_code == 200
    assert r.json()["data"] == {"has_app": True}


def test_ssr_page_serializes_plugin_registry_store():
    from basis.shared.component import Component
    from basis.server.app import Basis

    app = Basis()
    app.bootstrap()

    class Root(Component):
        template = "<div>hello {name}</div>"
        name = "world"

    from basis.shared.page import Page

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    client = TestClient(app)
    html = client.get("/demo").text
    assert 'id="basis-initial-state"' in html
    state = json.loads(html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0])
    assert "plugins" in state
    assert "items" in state["plugins"]


# ---------------------------------------------------------------------------
# ui-plugin-manager panel.
# ---------------------------------------------------------------------------

def test_plugin_manager_renders_registry_rows():
    from basis.shared.component import Component
    from basis.plugins.ui.plugin_manager.plugin_manager import PluginManager  # noqa: F401  (registers the element)
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()
    plugin = BasisPlugin(prefix="/chat", name="chat")

    @plugin.action
    async def hi():
        return "hi"

    app.include_plugin(plugin)

    class Root(Component):
        template = "<div><ui-plugin-manager></ui-plugin-manager></div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    html = TestClient(app).get("/demo").text
    assert "chat" in html
    assert "enabled" in html
    assert "Disable" in html
    assert "1 action(s)" in html


def test_plugin_manager_toggle_dispatches_disable_then_enable():
    from basis.plugins.ui.plugin_manager.plugin_manager import PluginManager

    comp = PluginManager()
    calls = []

    class FakeTarget:
        def __init__(self, name):
            self.name = name

        def getAttribute(self, key):
            return self.name

    class FakeEvent:
        currentTarget = FakeTarget("chat")

    class FakeStore:
        items = {"chat": {"state": "enabled"}}

        async def disable(self, name):
            calls.append(("disable", name))

        async def enable(self, name):
            calls.append(("enable", name))

    Store._registry["plugins"] = FakeStore()

    async def run(event):
        # toggle is synchronous (reads event.currentTarget during dispatch); it
        # schedules the async store action on the loop — let it complete.
        comp.toggle(event)
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    # enabled → disable
    asyncio.run(run(FakeEvent()))
    assert calls == [("disable", "chat")]

    # disabled → enable
    Store._registry["plugins"].items = {"chat": {"state": "disabled"}}
    asyncio.run(run(FakeEvent()))
    assert calls == [("disable", "chat"), ("enable", "chat")]

    # unknown plugin → no dispatch
    Store._registry["plugins"].items = {}
    asyncio.run(run(FakeEvent()))
    assert calls == [("disable", "chat"), ("enable", "chat")]


def test_ssr_direct_page_render_attaches_app_to_registry_swept_store():
    """Regression: Jotter's /ssr calls render_page_ssr(request, Page) with NO
    global_stores, so the plugins store enters via the registry sweep — it must
    still get the app attached + projection refreshed (the store-only-in-_get_all_stores
    attach missed this path → SSR serialized/rendered empty items)."""
    from fastapi import Request
    from fastapi.responses import HTMLResponse
    from basis.shared.component import Component
    from basis.server.ssr import render_page_ssr
    from basis.shared.page import Page
    import basis.plugins.ui.plugin_manager.plugin_manager  # noqa: F401

    app = Basis()
    app.bootstrap()
    plugin = BasisPlugin(prefix="/chat", name="chat")
    app.include_plugin(plugin)

    class Root(Component):
        template = "<div><ui-plugin-manager></ui-plugin-manager></div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    @app.get("/direct_ssr")
    async def direct_ssr(request: Request):
        html = await render_page_ssr(request, DemoPage)
        return HTMLResponse(html)

    html = TestClient(app).get("/direct_ssr").text
    assert "ui-plugin-manager-row" in html
    assert "chat" in html
    assert "Disable" in html
