"""``$device`` / ``$network`` — the core context stores.

The server has no authoritative source for either store, so the contract under test is
the SSR-safe one: neutral values that serialise, capability fields the browser answers
through a declared media query, and hydration that wins over both.
"""

import json

import pytest

from basis.shared import store as store_module
from basis.shared.breakpoints import compact_query, medium_query
from basis.shared.device import DeviceStore, ensure_device_store
from basis.shared.media import MediaQuery
from basis.shared.network import NetworkStore, ensure_network_store
from basis.shared.store import FRAMEWORK_STORE_NAMES, Store

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


class _Script:
    """Stand-in for the ``#basis-initial-state`` script tag."""

    def __init__(self, payload: str):
        self.textContent = payload


class _Document:
    """Stand-in for the client document, serving one initial-state payload."""

    def __init__(self, state: dict):
        self._state = state

    def getElementById(self, element_id: str):
        return _Script(json.dumps(self._state))


@pytest.fixture(autouse=True)
def isolate_registries(monkeypatch):
    """Store names and media-query runtime state are process-global: reset them."""
    monkeypatch.setattr(store_module, "_client_ready", False)
    monkeypatch.setattr(store_module, "document", None)
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
    declared = DeviceStore.declared_media()
    assert set(declared) == {"hover", "reduced_motion", "compact", "medium"}
    assert declared["hover"].query == "(hover: hover)"
    assert declared["hover"].default is True  # desktop-first neutral
    assert declared["reduced_motion"].query == "(prefers-reduced-motion: reduce)"
    assert declared["reduced_motion"].default is False
    # The tier boundaries come from the breakpoint contract, not from a literal here.
    assert declared["compact"].query == compact_query()
    assert declared["medium"].query == medium_query()
    assert declared["compact"].default is False  # "regular" until the browser answers


def test_declared_fields_are_real_fields_without_a_browser():
    """Declaration materialises the neutral, so the server renders and serialises it."""
    device = DeviceStore("device")
    assert device.__dict__["hover"] is True
    assert device.__dict__["reduced_motion"] is False


def test_hydrated_values_win_over_neutrals(monkeypatch):
    """``#basis-initial-state`` is authoritative — neither the declared default nor an
    ``__init__`` neutral may clobber it."""
    monkeypatch.setattr(
        store_module,
        "document",
        _Document({"device": {"hover": False, "reduced_motion": True, "width": 390}}),
    )

    device = DeviceStore("device")

    assert device._hydrated_from_ssr is True
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


def test_offline_is_the_inverse_of_online():
    network = NetworkStore("network")
    assert network.offline is False

    network.online = False
    assert network.offline is True


def test_offline_follows_a_hydrated_online(monkeypatch):
    monkeypatch.setattr(store_module, "document", _Document({"network": {"online": False}}))

    network = NetworkStore("network")

    assert network.online is False
    assert network.offline is True


def test_neutral_defaults_merge_across_inheritance():
    """A subclass extends the neutrals; the base declaration still applies."""

    class TabletStore(DeviceStore):
        neutral_defaults = {"density": "tablet"}

    store = TabletStore("tablet_device")

    assert store.density == "tablet"
    assert store.width == 0


def test_the_declaration_mapping_is_not_a_field():
    """Only the declared entries become fields."""
    assert "neutral_defaults" not in DeviceStore("device").serialize()
