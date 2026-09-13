"""The JS side of the client tests: a fake ``ffi`` that models Pyodide's proxies.

Server-side tests exercise client code against fakes, because the real ``window``/``ffi``
are absent under pytest. How faithfully the fake models a proxy matters: Pyodide's
``create_proxy`` returns a JS object that stays callable and is freed explicitly with
``destroy()``, so a fake that returns the bare Python function makes every proxy-lifetime
mistake invisible. :class:`FakeProxy` is an object for that reason.
"""

from __future__ import annotations


class FakeProxy:
    """A proxy as Pyodide models it: callable, and freed with ``destroy()``."""

    def __init__(self, fn, freed: list):
        self.fn = fn
        self.freed = freed

    def __call__(self, *args, **kwargs):
        return self.fn(*args, **kwargs)

    def destroy(self):
        self.freed.append(self)


class FakeFFI:
    """Stand-in for Pyodide's ``ffi``: what was proxied, created, and freed."""

    def __init__(self):
        self.created: list = []
        self.proxies: list[FakeProxy] = []
        self.destroyed: list[FakeProxy] = []

    def create_proxy(self, fn):
        self.created.append(fn)
        proxy = FakeProxy(fn, self.destroyed)
        self.proxies.append(proxy)
        return proxy
