"""``basis.shared.router`` — where the page is, and who gets to say so.

The browser is the authority on the current location and the *server* is the authority for
the first paint: the page stamps ``current_path`` from the request and ``Route.check_match``
fills ``params`` in the same render, both of which serialise into ``#basis-initial-state``.
So the store has two obligations, and they pull in opposite directions —

* hydration wins over the browser read (a hydrated store keeps what the server stamped), and
* the browser wins afterwards: every navigation edge it can report (``popstate``, and
  ``pageshow`` for a back/forward-cache restore) lands in the field, with no listener held
  by hand.
"""

import pytest

from basis.shared import events as events_module
from basis.shared import router as router_module
from basis.shared import store as store_module
from basis.shared.events import EventHub
from basis.shared.router import RouterStore
from basis.shared.store import Store, install_initial_state
from js_fakes import FakeFFI


class FakeEvent:
    """A browser event, as far as the router is concerned: it reads nothing from one."""

    def __init__(self, type):
        self.type = type
        self.target = None
        self.detail = None


class FakeAttached:
    """A JS event target, holding the registrations the browser would hold."""

    def __init__(self, name="document"):
        self.name = name
        self.listeners = []

    def addEventListener(self, event, proxy, options=None):
        self.listeners.append((event, proxy))

    def removeEventListener(self, event, proxy, capture=False):
        self.listeners = [row for row in self.listeners if row != (event, proxy)]

    def dispatch(self, event):
        """Deliver one event to everything registered, as the browser would."""
        delivered = 0
        for name, proxy in list(self.listeners):
            if name == event:
                proxy(FakeEvent(event))
                delivered += 1
        return delivered

    def events(self):
        return [name for name, _proxy in self.listeners]


class FakeHistory:
    def __init__(self):
        self.pushed = []
        self.back_calls = 0

    def pushState(self, state, title, url):
        self.pushed.append(url)

    def back(self):
        self.back_calls += 1


class FakeWindow(FakeAttached):
    """One window for both halves: the hub registers on it and the router reads it."""

    def __init__(self, pathname="/"):
        super().__init__("window")
        self.location = type("Location", (), {"pathname": pathname})()
        self.history = FakeHistory()


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Store registries, the hub registry and the browser globals are process-global."""
    monkeypatch.setattr(store_module, "_client_ready", False)
    install_initial_state({})
    monkeypatch.setattr(events_module, "document", FakeAttached("document"))
    monkeypatch.setattr(events_module, "ffi", FakeFFI())
    EventHub._instance_registry.clear()
    Store._registry.clear()
    yield
    EventHub._instance_registry.clear()
    Store._registry.clear()


@pytest.fixture
def browser(monkeypatch):
    """A client: one fake window the hub registers on and the store reads."""
    window = FakeWindow()
    monkeypatch.setattr(events_module, "window", window)
    monkeypatch.setattr(router_module, "window", window)
    yield window


def _attached_router():
    """A router store as the client attaches it — declarations live, one registration each."""
    store = RouterStore("router")
    store.on_client_ready()
    return store


def test_a_client_built_store_reads_the_browser(browser):
    """No server state to hydrate from, so the browser is the only authority there is."""
    browser.location.pathname = "/dashboard"
    assert _attached_router().current_path == "/dashboard"


def test_hydration_wins_over_the_browser_read(monkeypatch, browser):
    """The page stamped ``current_path`` and ``Route`` filled ``params`` on the server;
    constructing the store on the client must not throw either away."""
    install_initial_state(
        {"router": {"current_path": "/users/7", "params": {"user_id": "7"}}}
    )
    browser.location.pathname = "/"           # what the browser would have said

    store = _attached_router()

    assert store._initial_load.snapshot_applied is True
    assert store.current_path == "/users/7"
    assert store.params == {"user_id": "7"}


def test_without_a_browser_the_path_is_the_neutral(monkeypatch):
    """SSR: the store cannot know the request's path — the page stamps it — so it ships
    the neutral and registers nothing."""
    monkeypatch.setattr(router_module, "window", None)
    store = _attached_router()
    assert store.current_path == ""
    assert store.params == {}


def test_popstate_rereads_the_path(browser):
    """One declaration, one registration, and the field follows the browser."""
    store = _attached_router()
    browser.location.pathname = "/settings"

    assert browser.dispatch("popstate") == 1
    assert store.current_path == "/settings"


def test_pageshow_rereads_the_path_after_a_restore(browser):
    """A page restored from the back/forward cache comes back on its entry's URL, which
    need not be the URL this document was frozen with."""
    store = _attached_router()
    browser.location.pathname = "/reports"

    assert browser.dispatch("pageshow") == 1
    assert store.current_path == "/reports"


def test_navigate_pushes_because_nothing_else_will(browser):
    """``pushState`` fires no event, so the field write is the caller's job."""
    store = _attached_router()
    store.navigate("/b")
    assert browser.history.pushed == ["/b"]
    assert store.current_path == "/b"


def test_back_leaves_the_write_to_popstate(browser):
    """``history.back()`` does fire one, so there is nothing to write here."""
    store = _attached_router()
    store.current_path = "/a"

    store.back()

    assert browser.history.back_calls == 1
    assert store.current_path == "/a"


def test_teardown_releases_both_registrations(browser):
    """The store's own teardown path is what frees them — no proxy outlives the store."""
    store = _attached_router()
    assert sorted(set(browser.events())) == ["pageshow", "popstate"]

    store.on_client_teardown()

    assert browser.listeners == []
