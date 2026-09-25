"""``$device`` / ``$network`` — the core context stores.

The server has no authoritative source for either store, so the contract under test is
the SSR-safe one: neutral values that serialise, capability fields the browser answers
through a declared media query, and hydration that wins over both.
"""

import pytest

from basis.shared import store as store_module
from basis.shared.device import DeviceStore, ensure_device_store
from basis.shared.events import declared_declarations
from basis.shared.media import MediaQuery
from basis.shared.network import NetworkStore, ensure_network_store
from basis.shared.page import Page, StaticPage
from basis.shared.store import FRAMEWORK_STORE_NAMES, Store, install_initial_state
from basis.shared.styling import HOVER_QUERY, compact_query, medium_query

DEVICE_NEUTRALS = {
    "width": 0,
    "height": 0,
    "dpr": 1,
    "orientation": "portrait",
    "pointer": "fine",
    "touch": False,
    "hover": True,
    "reduced_motion": False,
}

NETWORK_NEUTRALS = {
    "online": True,
    "effective_type": "unknown",
    "save_data": False,
}


@pytest.fixture(autouse=True)
def isolate_registries(monkeypatch):
    """Store names and media-query runtime state are process-global: reset them."""
    monkeypatch.setattr(store_module, "_client_ready", False)
    install_initial_state({})
    Store._registry.clear()
    Store._store_blueprints.clear()
    for query in list(MediaQuery._instance_registry.values()):
        query.mql = None
        query.listener = None
        query.targets = []
    yield
    Store._registry.clear()
    Store._store_blueprints.clear()


def test_both_stores_are_framework_guaranteed():
    """Page serialises them on every page, including a strict ``Page.stores`` page."""
    assert "device" in FRAMEWORK_STORE_NAMES
    assert "network" in FRAMEWORK_STORE_NAMES


def test_device_neutral_defaults_serialise():
    state = DeviceStore("device").serialize()
    for field, neutral in DEVICE_NEUTRALS.items():
        assert state[field] == neutral, field


def test_network_neutral_defaults_serialise():
    state = NetworkStore("network").serialize()
    for field, neutral in NETWORK_NEUTRALS.items():
        assert state[field] == neutral, field


def test_capability_fields_are_declared_media_queries():
    """``hover`` / ``reduced_motion`` / the viewport tier are media features."""
    declared = declared_declarations(DeviceStore)
    assert {"hover", "reduced_motion", "compact", "medium"} <= set(declared)
    assert DeviceStore.__dict__["hover"].query == HOVER_QUERY
    assert DeviceStore.__dict__["hover"].default is True  # desktop-first neutral
    assert DeviceStore.__dict__["reduced_motion"].query == "(prefers-reduced-motion: reduce)"
    assert DeviceStore.__dict__["reduced_motion"].default is False
    # The tier boundaries come from the breakpoint contract, not from a literal here.
    assert DeviceStore.__dict__["compact"].query == compact_query()
    assert DeviceStore.__dict__["medium"].query == medium_query()
    assert DeviceStore.__dict__["compact"].default is False  # "regular" until the browser answers
    # Each is a level: the browser's answer is written into the field.
    assert declared["hover"][0].kind == "level"
    assert declared["compact"][0].neutral is False


def test_declared_fields_are_real_fields_without_a_browser():
    """Declaration materialises the neutral, so the server renders and serialises it."""
    device = DeviceStore("device")
    assert device.__dict__["hover"] is True
    assert device.__dict__["reduced_motion"] is False


def test_hydrated_values_win_over_neutrals(monkeypatch):
    """``#basis-initial-state`` is authoritative — neither the declared default nor an
    ``__init__`` neutral may clobber it."""
    install_initial_state(
        {"device": {"hover": False, "reduced_motion": True, "width": 390}}
    )

    device = DeviceStore("device")

    assert device._initial_load.snapshot_applied is True
    assert device.hover is False
    assert device.reduced_motion is True
    assert device.width == 390
    assert device.height == 0  # a key the payload omits keeps its neutral


def test_ensure_helpers_resolve_one_instance_per_name():
    device = ensure_device_store()
    network = ensure_network_store()
    assert type(device) is DeviceStore
    assert type(network) is NetworkStore
    assert ensure_device_store() is device


@pytest.mark.parametrize("page_base", [Page, StaticPage])
def test_explicit_page_subset_keeps_specialized_context_stores(page_base):
    class ContextPage(page_base):
        stores = ["device", "network"]

    ContextPage._ensure_stores()
    device = Store._registry["device"]
    network = Store._registry["network"]
    ContextPage._ensure_stores()

    assert type(device) is DeviceStore
    assert type(network) is NetworkStore
    assert Store._registry["device"] is device
    assert Store._registry["network"] is network


def test_offline_is_the_inverse_of_online():
    network = NetworkStore("network")
    assert network.offline is False

    network.online = False
    assert network.offline is True


def test_offline_follows_a_hydrated_online(monkeypatch):
    install_initial_state({"network": {"online": False}})

    network = NetworkStore("network")

    assert network.online is False
    assert network.offline is True


def test_state_defaults_merge_across_inheritance():
    """A subclass extends state; the base declarations still apply."""

    class TabletStore(DeviceStore):
        density = "tablet"

    store = TabletStore("tablet_device")

    assert store.density == "tablet"
    assert store.width == 0


def test_the_declaration_mapping_is_not_a_field():
    """Only the declared entries become fields."""
    assert "neutral_defaults" not in DeviceStore("device").serialize()
