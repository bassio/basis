"""
Region primitive tests (ROADMAP-SPATIAL.md Tier A1/A2).

Covers: the app-level ``add_to_region`` API (class-as-identity, replace-on-
readd, ordering), the ``$regions`` RegionStore projection, the plugin flush /
unwind lifecycle (``@plugin.region`` / ``plugin.add_to_region`` recorded on
``PluginRegistration.region_items``), ``resolve_component`` / ``mount_component``,
and an end-to-end SSR render where a ``<ui-region>`` mounts a contributed
component's HTML.
"""
import json

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis, _synthesize_page
from basis.server.plugin import BasisPlugin
from basis.shared.component import Component
from basis.shared.store import Store

# Register the <ui-region> custom element / component class so templates that
# reference the tag resolve it as a child component (server + client).
import basis.ui.region.region  # noqa: F401


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


class StatusPill(Component):
    text = ""

    def template(self):
        """
        <span class="status-pill">{text}</span>
        """


class MetricStatus(Component):
    metric = ""
    value = ""

    def template(self):
        """
        <span class="metric">{metric}: {value}</span>
        """


def _listing(app):
    from basis.shared.region import _region_listing
    return _region_listing(app)


# ---------------------------------------------------------------------------
# App-level registry (class-as-identity, replace, ordering, removal).
# ---------------------------------------------------------------------------

def test_add_to_region_registers_and_store_projects():
    app = Basis()
    app.bootstrap()
    app.add_to_region("statusbar-right", StatusPill, props={"text": "synced"})

    listing = _listing(app)
    assert "statusbar-right" in listing
    entry = listing["statusbar-right"][0]
    assert entry["cls_path"] == f"{StatusPill.__module__}.StatusPill"
    assert entry["props"] == {"text": "synced"}

    # The $regions store (app-owned) projects the same listing.
    store = app.regions
    store._refresh_from_app()
    assert store.items_for("statusbar-right")[0]["cls_path"].endswith(".StatusPill")


def test_duplicate_class_same_region_replaces():
    app = Basis()
    app.add_to_region("statusbar-right", StatusPill, props={"text": "first"})
    app.add_to_region("statusbar-right", StatusPill, props={"text": "second"})
    items = app._regions["statusbar-right"]
    assert len(items) == 1  # class-as-identity → replace, not duplicate
    assert items[0].props == {"text": "second"}


def test_ordering_default_then_order_then_position_start():
    app = Basis()
    app.add_to_region("bar", StatusPill)
    app.add_to_region("bar", MetricStatus, order=1)
    app.add_to_region("bar", MetricStatus, order=1)  # replaced (same class) → no dup
    app.add_to_region("bar", StatusPill, position="start")  # replaced → no dup
    # Re-add distinct classes with different orders:
    app._regions.clear()
    app.add_to_region("bar", StatusPill)                       # natural (append)
    app.add_to_region("bar", MetricStatus, order=1)            # explicit order
    app.add_to_region("bar", StatusPill, position="start")     # prepend

    paths = [c.cls_path for c in app._regions["bar"]]
    # position="start" (MIN_ORDER) first, then order=1, then natural append last.
    assert paths[0].endswith(".StatusPill")
    assert paths[1].endswith(".MetricStatus")
    assert len(paths) == 2  # the first StatusPill was replaced by the prepend


def test_remove_from_region_and_handle_dispose():
    app = Basis()
    handle = app.add_to_region("sidebar", MetricStatus, props={"metric": "cpu"})
    assert app._regions["sidebar"]

    handle.dispose()
    assert not app._regions["sidebar"]

    app.add_to_region("sidebar", MetricStatus)
    assert app.remove_from_region("sidebar", MetricStatus) is True
    assert not app._regions["sidebar"]


# ---------------------------------------------------------------------------
# resolve_component / mount_component.
# ---------------------------------------------------------------------------

def test_resolve_component_round_trip():
    from basis.shared.region import cls_path_of, resolve_component
    cls_path = cls_path_of(StatusPill)
    assert resolve_component(cls_path) is StatusPill


def test_mount_component_by_cls_path_into_element():
    from basis.shared.region import mount_component
    from basis.server.tree_builder import html_to_element

    container = html_to_element("<div id='host'></div>")
    inst = mount_component(container, f"{StatusPill.__module__}.StatusPill", {"text": "hi"})
    assert inst.__element__.tagName.lower() == "span"
    assert inst.text == "hi"


# ---------------------------------------------------------------------------
# Plugin flush / unwind (revertible registration).
# ---------------------------------------------------------------------------

def test_plugin_region_flushes_on_include_and_unwinds_on_remove():
    app = Basis()
    plugin = BasisPlugin(prefix="/demo", name="demo")

    @plugin.region("activity")
    class DemoIcon(Component):
        def template(self):
            return "<div class='demo-icon'>icon</div>"

    plugin.add_to_region("sidebar", MetricStatus, props={"metric": "mem"})

    app.include_plugin(plugin)
    assert f"{DemoIcon.__module__}.DemoIcon" in {c.cls_path for c in app._regions["activity"]}
    assert any(c.cls_path.endswith(".MetricStatus") for c in app._regions["sidebar"])

    # disable → region contributions unwound.
    import asyncio
    asyncio.run(app.remove_plugin("demo"))
    assert not app._regions["activity"]
    assert not app._regions["sidebar"]

    # enable → re-registered (include_plugin re-flushes the pending list).
    asyncio.run(app.enable_plugin("demo"))
    assert f"{DemoIcon.__module__}.DemoIcon" in {c.cls_path for c in app._regions["activity"]}


# ---------------------------------------------------------------------------
# RegionStore local (client-side ephemeral) add/remove.
# ---------------------------------------------------------------------------

def test_region_store_add_local_and_remove_local():
    from basis.shared.region import RegionStore
    store = RegionStore("regions")
    store.add_local("statusbar-right", "demo.StatusPill", {"text": "x"}, order=1)
    store.add_local("statusbar-right", "demo.StatusPill", {"text": "y"})  # replace
    assert len(store.items_for("statusbar-right")) == 1
    store.remove_local("statusbar-right", "demo.StatusPill")
    assert store.items_for("statusbar-right") == []


# ---------------------------------------------------------------------------
# End-to-end SSR render: <ui-region> mounts a contributed component's HTML.
# ---------------------------------------------------------------------------

def test_ssr_renders_region_items():
    app = Basis()
    app.bootstrap()

    class Root(Component):
        """
        <div class="app-root">
            <ui-region name="statusbar-right"></ui-region>
        </div>
        """

    app.add_to_region("statusbar-right", StatusPill, props={"text": "synced"})
    app.add_to_region("statusbar-right", MetricStatus, props={"metric": "cpu", "value": "12%"})

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200

    # The region's contributions are rendered server-side (single-pass mount).
    assert 'data-region-name="statusbar-right"' in resp.text
    # The mounted roots carry data-region-item markers, so assert on content
    # (the exact opening tag also carries that injected attribute).
    assert 'class="status-pill"' in resp.text
    assert ">synced</span>" in resp.text
    assert 'class="metric"' in resp.text
    assert ">cpu: 12%</span>" in resp.text
    # data-region-item markers on the mounted roots (client reconciliation key).
    assert 'data-region-item="' in resp.text

    # The $regions store is serialized into #basis-initial-state (app-housed).
    html = resp.text
    state = json.loads(
        html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0]
    )
    assert "regions" in state
    assert "statusbar-right" in state["regions"]["items"]
