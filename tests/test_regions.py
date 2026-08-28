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
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.page import _synthesize_page
from basis.server.plugin import BasisPlugin
from basis.shared.component import Component
from basis.shared.store import Store

# The official regions plugin provides the <ui-region> custom element, the
# $regions store and the contribution API (app-level add_to_region moved into
# the plugin space — REGIONS-PLUGIN-PLAN.md D2).
from basis.plugins.regions import regions_plugin
# Register the <ui-region> custom element / component class so templates that
# reference the tag resolve it as a child component (server + client).
import basis.plugins.regions.region  # noqa: F401


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
    from basis.plugins.regions.registry import _region_listing
    return _region_listing(app)


# ---------------------------------------------------------------------------
# App-level registry (class-as-identity, replace, ordering, removal).
# ---------------------------------------------------------------------------

def test_add_to_region_registers_and_store_projects():
    app = Basis()
    app.bootstrap()
    regions_plugin.add_to_region("statusbar-right", StatusPill, props={"text": "synced"})

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
    app.bootstrap()
    regions_plugin.add_to_region("statusbar-right", StatusPill, props={"text": "first"})
    regions_plugin.add_to_region("statusbar-right", StatusPill, props={"text": "second"})
    items = app._regions["statusbar-right"]
    assert len(items) == 1  # class-as-identity → replace, not duplicate
    assert items[0].props == {"text": "second"}


def test_ordering_default_then_order_then_position_start():
    app = Basis()
    app.bootstrap()
    regions_plugin.add_to_region("bar", StatusPill)
    regions_plugin.add_to_region("bar", MetricStatus, order=1)
    regions_plugin.add_to_region("bar", MetricStatus, order=1)  # replaced (same class) → no dup
    regions_plugin.add_to_region("bar", StatusPill, position="start")  # replaced → no dup
    # Re-add distinct classes with different orders:
    app._regions.clear()
    regions_plugin.add_to_region("bar", StatusPill)                   # natural (append)
    regions_plugin.add_to_region("bar", MetricStatus, order=1)        # explicit order
    regions_plugin.add_to_region("bar", StatusPill, position="start")  # prepend

    paths = [c.cls_path for c in app._regions["bar"]]
    # position="start" (MIN_ORDER) first, then order=1, then natural append last.
    assert paths[0].endswith(".StatusPill")
    assert paths[1].endswith(".MetricStatus")
    assert len(paths) == 2  # the first StatusPill was replaced by the prepend


def test_remove_from_region_and_handle_dispose():
    app = Basis()
    app.bootstrap()
    handle = regions_plugin.add_to_region("sidebar", MetricStatus, props={"metric": "cpu"})
    assert app._regions["sidebar"]

    handle.dispose()
    assert not app._regions["sidebar"]

    regions_plugin.add_to_region("sidebar", MetricStatus)
    assert regions_plugin.remove_from_region("sidebar", MetricStatus) is True
    assert not app._regions["sidebar"]


# ---------------------------------------------------------------------------
# resolve_component / mount_component.
# ---------------------------------------------------------------------------

def test_resolve_component_round_trip():
    from basis.plugins.regions.registry import cls_path_of, resolve_component
    cls_path = cls_path_of(StatusPill)
    assert resolve_component(cls_path) is StatusPill


def test_mount_component_by_cls_path_into_element():
    from basis.plugins.regions.registry import mount_component
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
    from basis.plugins.regions.store import RegionStore
    store = RegionStore("regions")
    store.add_local("statusbar-right", "demo.StatusPill", {"text": "x"}, order=1)
    store.add_local("statusbar-right", "demo.StatusPill", {"text": "y"})  # replace
    assert len(store.items_for("statusbar-right")) == 1
    store.remove_local("statusbar-right", "demo.StatusPill")
    assert store.items_for("statusbar-right") == []


def test_region_store_add_local_replaces_in_place_does_not_reorder():
    """Regression: re-adding an existing contribution must replace it IN PLACE.

    A contribution's module can be imported lazily *while* the region mounts it
    (``resolve_component``), which re-runs ``@plugin.region`` and calls
    ``add_local`` again. The old remove+re-append implementation moved the
    contribution to the end, silently flipping the region order on the client
    (the TeamExplorer jumped above the regions_demo banner after hydration).
    The hydrated ``#basis-initial-state`` order is authoritative on boot.
    """
    from basis.plugins.regions.store import RegionStore
    store = RegionStore("regions")
    store.__dict__["items"] = {
        "workspace-center": [
            {"cls_path": "myapp.plugins.regions_demo.RegionDemoBanner", "props": {}, "order": None},
            {"cls_path": "myapp.plugins.heroes.TeamExplorer", "props": {}, "order": None},
        ]
    }

    # Simulate the lazy import of regions_demo happening while the region
    # mounts its contributions (the banner gets re-registered mid-flight).
    store.add_local("workspace-center", "myapp.plugins.regions_demo.RegionDemoBanner", props={"p": 1})

    assert [it["cls_path"] for it in store.items_for("workspace-center")] == [
        "myapp.plugins.regions_demo.RegionDemoBanner",
        "myapp.plugins.heroes.TeamExplorer",
    ]
    # The replaced entry keeps its position AND its updated props.
    assert store.items_for("workspace-center")[0]["props"] == {"p": 1}

    # A genuinely new contribution appends at the end.
    store.add_local("workspace-center", "x.New")
    assert [it["cls_path"] for it in store.items_for("workspace-center")][-1] == "x.New"


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

    regions_plugin.add_to_region("statusbar-right", StatusPill, props={"text": "synced"})
    regions_plugin.add_to_region("statusbar-right", MetricStatus, props={"metric": "cpu", "value": "12%"})

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


def test_ssr_renders_region_items_in_declared_order():
    """Contributions render in declaration order — a re-registration must never
    silently reorder the region (this is the SSR-side contract of the client
    ``add_local`` in-place fix)."""
    app = Basis()
    app.bootstrap()

    class Root(Component):
        """
        <div class="app-root">
            <ui-region name="statusbar-right"></ui-region>
        </div>
        """

    regions_plugin.add_to_region("statusbar-right", StatusPill, props={"text": "synced"})
    regions_plugin.add_to_region("statusbar-right", MetricStatus, props={"metric": "cpu", "value": "12%"})

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200

    markers = re.findall(r'data-region-item="([^"]+)"', resp.text)
    assert [m.rsplit(".", 1)[-1] for m in markers] == ["StatusPill", "MetricStatus"]
