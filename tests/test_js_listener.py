"""Unit tests for ``basis.shared.js.Listener``.

The listener is the one place a JS registration and its proxy are taken apart, so what it
owes its callers is asserted directly: unbinding and freeing are separate steps, freeing
happens once, and without a browser nothing is bound at all.
"""

import pytest

import basis.shared.js as js
from js_fakes import FakeFFI


class FakeTarget:
    """A JS event target: the registration list, as the browser would keep it."""

    def __init__(self):
        self.listeners = []
        self.removed = []

    def addEventListener(self, event, proxy):
        self.listeners.append((event, proxy))

    def removeEventListener(self, event, proxy):
        self.removed.append((event, proxy))
        self.listeners = [pair for pair in self.listeners if pair != (event, proxy)]


@pytest.fixture
def fake_ffi(monkeypatch):
    ffi = FakeFFI()
    monkeypatch.setattr(js, "ffi", ffi)
    return ffi


def test_a_listener_binds_the_proxy_it_keeps(fake_ffi):
    target = FakeTarget()
    seen = []

    listener = js.Listener(target, "resize", lambda event=None: seen.append(event))

    assert target.listeners == [("resize", listener.proxy)]
    assert len(fake_ffi.created) == 1
    listener.proxy("an event")
    assert seen == ["an event"]


def test_detach_unbinds_and_keeps_the_proxy(fake_ffi):
    """What a one-shot handler calls on itself: the proxy outlives the call."""
    target = FakeTarget()

    listener = js.Listener(target, "basis:connected", lambda event=None: None)
    proxy = listener.proxy

    listener.detach()

    assert target.listeners == []
    assert target.removed == [("basis:connected", proxy)]
    assert listener.proxy is proxy  # still held, so the browser's call cannot dangle
    assert fake_ffi.destroyed == []


def test_dispose_unbinds_and_frees(fake_ffi):
    target = FakeTarget()

    listener = js.Listener(target, "resize", lambda event=None: None)
    proxy = listener.proxy

    listener.dispose()

    assert target.listeners == []
    assert target.removed == [("resize", proxy)]
    assert fake_ffi.destroyed == [proxy]
    assert listener.proxy is None


def test_dispose_after_detach_still_frees(fake_ffi):
    """The one-shot flow: the handler unbinds, the caller disposes, nothing leaks."""
    target = FakeTarget()

    listener = js.Listener(target, "basis:connected", lambda event=None: None)
    proxy = listener.proxy

    listener.detach()
    listener.dispose()

    # Unbinding twice is a no-op in the browser; the point is that the proxy is freed.
    assert target.listeners == []
    assert fake_ffi.destroyed == [proxy]


def test_dispose_is_idempotent(fake_ffi):
    target = FakeTarget()

    listener = js.Listener(target, "resize", lambda event=None: None)
    listener.dispose()
    listener.dispose()

    assert len(fake_ffi.destroyed) == 1
    assert len(target.removed) == 1


def test_an_absent_target_binds_nothing(fake_ffi):
    """A JS API this browser does not have reads as a falsy value, not as None."""
    listener = js.Listener(None, "change", lambda event=None: None)

    assert listener.proxy is None
    assert fake_ffi.created == []
    listener.detach()
    listener.dispose()
    assert fake_ffi.destroyed == []


def test_without_a_browser_a_listener_is_inert(monkeypatch):
    target = FakeTarget()
    monkeypatch.setattr(js, "ffi", None)

    listener = js.Listener(target, "resize", lambda event=None: None)

    assert listener.proxy is None
    assert target.listeners == []
    listener.dispose()
