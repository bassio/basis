"""Unit tests for the client context probes (``basis.client.device_probes``).

The probes are client-only, so they run here against a fake window — the same approach
the media-query tests take. What matters is asserted directly: the browser's answers
reach the stores, an absent API leaves the neutral, and the release/resume cycle leaves
no binding behind.
"""

import pytest

import basis.client.device_probes as probes
from basis.shared import js as js_module
from basis.shared import reactive
from basis.shared import store as store_module
from basis.shared.device import DeviceStore
from basis.shared.network import NetworkStore
from basis.shared.store import Store
from js_fakes import FakeFFI


class FakeMediaQueryList:
    def __init__(self, query):
        self.query = query
        self.matches = False


class FakeConnection:
    def __init__(self):
        self.effectiveType = "4g"
        self.saveData = False
        self.listeners = []
        self.removed = []

    def addEventListener(self, event, proxy):
        self.listeners.append((event, proxy))

    def removeEventListener(self, event, proxy):
        self.removed.append((event, proxy))
        self.listeners = [pair for pair in self.listeners if pair != (event, proxy)]

    def fired(self, event, arg=None):
        """Invoke the proxy bound for *event*, as the browser would."""
        [proxy for name, proxy in self.listeners if name == event][0](arg)


class FakeNavigator:
    def __init__(self):
        self.onLine = True
        self.maxTouchPoints = 0
        self.connection = FakeConnection()


class FakeWindow:
    def __init__(self):
        self.innerWidth = 1280
        self.innerHeight = 800
        self.devicePixelRatio = 2
        self.navigator = FakeNavigator()
        self.queries = {}
        self.listeners = []
        self.removed = []

    def matchMedia(self, query):
        return self.queries.setdefault(query, FakeMediaQueryList(query))

    def answer(self, query, value):
        """Answer *query* before anything asks for it."""
        self.matchMedia(query).matches = value

    def addEventListener(self, event, proxy):
        self.listeners.append((event, proxy))

    def removeEventListener(self, event, proxy):
        self.removed.append((event, proxy))
        self.listeners = [pair for pair in self.listeners if pair != (event, proxy)]

    def bound_events(self):
        return sorted(name for name, _proxy in self.listeners)

    def removed_events(self):
        return sorted(name for name, _proxy in self.removed)

    def fired(self, event, arg=None):
        """Invoke the proxy bound for *event*, as the browser would."""
        [proxy for name, proxy in self.listeners if name == event][0](arg)


@pytest.fixture
def browser(monkeypatch):
    """Run the probes against a fake window, from clean module + store state."""
    win, fake_ffi = FakeWindow(), FakeFFI()
    monkeypatch.setattr(probes, "window", win)
    monkeypatch.setattr(js_module, "ffi", fake_ffi)
    monkeypatch.setattr(probes, "PYSCRIPT", True)
    monkeypatch.setattr(probes, "_installed", False)
    monkeypatch.setattr(probes, "_lifecycle_installed", False)
    monkeypatch.setattr(store_module, "_client_ready", False)
    probes._bindings.clear()
    probes._lifecycle_bindings.clear()
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield win
    probes._bindings.clear()
    probes._lifecycle_bindings.clear()
    Store._registry.clear()
    Store._store_blueprints.clear()


def test_install_reads_the_browser_environment(browser):
    win = browser
    win.answer("(orientation: portrait)", True)
    win.answer("(pointer: coarse)", True)
    win.navigator.maxTouchPoints = 5
    win.navigator.onLine = False
    win.navigator.connection.effectiveType = "2g"
    win.navigator.connection.saveData = True

    probes.install_device_probes()

    device = Store._registry.get("device")
    network = Store._registry.get("network")
    assert (device.width, device.height, device.dpr) == (1280, 800, 2)
    assert device.orientation == "portrait"
    assert device.pointer == "coarse"
    assert device.touch is True
    assert network.online is False
    assert network.offline is True  # derived, and already correct on first read
    assert network.effective_type == "2g"
    assert network.save_data is True


def test_install_is_idempotent(browser):
    win = browser

    probes.install_device_probes()
    probes.install_device_probes()

    assert win.bound_events() == [
        "offline",
        "online",
        "orientationchange",
        "pagehide",
        "pageshow",
        "resize",
    ]
    assert len(win.navigator.connection.listeners) == 1


def test_a_viewport_change_re_reads(browser):
    win = browser
    probes.install_device_probes()
    device = Store._registry.get("device")

    win.innerWidth = 390
    win.innerHeight = 844
    win.answer("(orientation: portrait)", True)
    win.fired("resize")

    assert (device.width, device.height) == (390, 844)
    assert device.orientation == "portrait"


def test_a_connectivity_change_re_reads(browser):
    win = browser
    probes.install_device_probes()
    network = Store._registry.get("network")
    assert network.offline is False

    win.navigator.onLine = False
    win.fired("offline")
    assert network.offline is True

    win.navigator.connection.effectiveType = "2g"
    win.navigator.connection.fired("change")
    assert network.effective_type == "2g"


def test_absent_connection_api_keeps_the_neutral(browser):
    win = browser
    win.navigator.connection = None

    probes.install_device_probes()

    network = Store._registry.get("network")
    assert network.online is True
    assert network.effective_type == "unknown"
    assert network.save_data is False
    assert "change" not in win.bound_events()


class NavigatorWithoutConnection:
    """A navigator whose missing property raises, as Pyodide may on Firefox.

    ``navigator.connection`` is Chromium-only: a browser without it may read as a falsy
    value or raise ``AttributeError`` on the property itself. Neither may cost us the
    probe — Firefox has no such property at all.
    """

    def __init__(self):
        self.onLine = True
        self.maxTouchPoints = 0

    def __getattr__(self, name):
        raise AttributeError(name)


def test_a_connection_property_that_raises_does_not_break_the_install(browser):
    """The whole probe set must survive one absent browser API."""
    win = browser
    win.navigator = NavigatorWithoutConnection()

    probes.install_device_probes()

    # Every other binding is live, and the probe ran to completion.
    assert win.bound_events() == [
        "offline",
        "online",
        "orientationchange",
        "pagehide",
        "pageshow",
        "resize",
    ]
    device = Store._registry.get("device")
    network = Store._registry.get("network")
    assert device.width == 1280
    assert network.online is True
    assert network.effective_type == "unknown"


def test_probe_writes_nothing_when_nothing_moved(browser, monkeypatch):
    browser  # install against the fake window
    probes.install_device_probes()
    device = Store._registry.get("device")
    triggered = []
    monkeypatch.setattr(
        device._dag, "trigger_batch", lambda names: triggered.append(sorted(names))
    )

    probes._probe()

    assert triggered == []


def test_one_probe_cycle_is_one_flush(browser, monkeypatch):
    """One environment change: only the moved fields react, and only once."""
    win = browser
    probes.install_device_probes()
    device = Store._registry.get("device")
    network = Store._registry.get("network")
    batches = []
    monkeypatch.setattr(
        device._dag, "trigger_batch", lambda names: batches.append(("device", sorted(names)))
    )
    monkeypatch.setattr(
        network._dag, "trigger_batch", lambda names: batches.append(("network", sorted(names)))
    )
    drains = []
    monkeypatch.setattr(reactive, "_drain_pending", lambda: drains.append(1))

    win.innerWidth = 390
    win.navigator.onLine = False
    probes._probe()

    # Each store reacts once, with only the field that moved; the drain happens once
    # (refrains exit innermost-first, so the trigger order is incidental).
    assert sorted(batches) == [("device", ["width"]), ("network", ["online"])]
    assert len(drains) == 1


def test_pagehide_releases_bindings_and_store_client_state(browser, monkeypatch):
    win = browser
    released = []
    monkeypatch.setattr(DeviceStore, "on_client_teardown", lambda self: released.append("device"))
    monkeypatch.setattr(NetworkStore, "on_client_teardown", lambda self: released.append("network"))
    probes.install_device_probes()
    bound = [binding.proxy for binding in probes._bindings]

    win.fired("pagehide")

    assert sorted(released) == ["device", "network"]
    assert probes._installed is False
    # The lifecycle pair stays: it is the only way back after a restore.
    assert win.bound_events() == ["pagehide", "pageshow"]
    assert win.removed_events() == ["offline", "online", "orientationchange", "resize"]
    # Unbinding drops the browser's reference to the handler; the proxy is a JS object
    # that outlives it until it is destroyed explicitly.
    assert js_module.ffi.destroyed == bound


def test_pageshow_resumes_after_a_pagehide(browser, monkeypatch):
    win = browser
    resumed = []
    monkeypatch.setattr(DeviceStore, "on_client_ready", lambda self: resumed.append("device"))
    monkeypatch.setattr(NetworkStore, "on_client_ready", lambda self: resumed.append("network"))
    probes.install_device_probes()
    win.fired("pagehide")

    win.innerWidth = 390  # moved while the page was frozen
    win.fired("pageshow")

    assert probes._installed is True
    assert sorted(resumed) == ["device", "network"]
    assert Store._registry.get("device").width == 390


def test_pageshow_without_a_pagehide_changes_nothing(browser, monkeypatch):
    win = browser
    resumed = []
    monkeypatch.setattr(DeviceStore, "on_client_ready", lambda self: resumed.append("device"))
    probes.install_device_probes()

    win.fired("pageshow")

    assert resumed == []


def test_teardown_is_idempotent(browser):
    browser
    probes.install_device_probes()
    probes.teardown_device_probes()
    probes.teardown_device_probes()
    assert probes._installed is False


def test_probes_are_inert_without_pyscript(browser, monkeypatch):
    win = browser
    monkeypatch.setattr(probes, "PYSCRIPT", False)

    probes.install_device_probes()
    probes.teardown_device_probes()

    assert win.listeners == []
    assert Store._registry.get("device") is None
    assert Store._registry.get("network") is None
