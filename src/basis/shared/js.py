"""The Python↔JS event boundary: bind a callback, and normalise what it receives.

A Python handler reaches a JS ``EventTarget`` through two objects with one lifetime: the
``addEventListener`` registration, and the ``ffi.create_proxy`` handle the browser holds
the callback through. Releasing one without the other fails silently — an unfreed proxy
leaks, and a dropped one leaves the browser calling a handler that can no longer run.
:class:`Listener` owns both.

:func:`py_event` is the other half: a handler receives the raw JS event unless it is
wrapped, in which case a ``CustomEvent``'s ``detail`` arrives as a Python dict or list and
an ``async`` handler is scheduled rather than dropped.

Client-only in effect, importable everywhere in practice: with no Pyodide there is no
``ffi``, so every listener is inert and the server imports this module like any other
shared one.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from functools import wraps

IS_CLIENT = "pyscript" in sys.modules or "pyodide" in sys.modules

if IS_CLIENT:
    try:
        from pyscript import ffi
    except ImportError:
        ffi = None
else:
    ffi = None


class Listener:
    """One handler bound to one JS event target. Inert without a browser."""

    def __init__(self, target, event: str, handler):
        self.target = target
        self.event = event
        # A JS API this browser does not have reads as a falsy value, not as None.
        self.proxy = ffi.create_proxy(handler) if ffi is not None and target else None
        if self.proxy is not None:
            target.addEventListener(event, self.proxy)

    def detach(self) -> None:
        """Unbind, keeping the proxy alive.

        This is what a one-shot handler calls on itself: unbinding the registration it
        is currently running through is ordinary, freeing the proxy underneath that call
        is not.
        """
        if self.proxy is None:
            return
        self.target.removeEventListener(self.event, self.proxy)

    def dispose(self) -> None:
        """Unbind and free the proxy. Idempotent; call it from outside the handler."""
        proxy = self.proxy
        if proxy is None:
            return
        self.proxy = None
        self.target.removeEventListener(self.event, proxy)
        proxy.destroy()


class PythonEventWrapper:
    """A JS event as Python sees it: ``detail`` converted, everything else delegated."""

    def __init__(self, original_event):
        self._original_event = original_event
        detail = getattr(original_event, "detail", None)
        if detail is not None and hasattr(detail, "to_py"):
            self.detail = detail.to_py()
        else:
            self.detail = detail

    def __getattr__(self, name):
        return getattr(self._original_event, name)


def py_event(func):
    """Wrap an event handler so the JS event it receives arrives as Python data.

    A handler is called positionally (``handler(self, event)``) or by keyword
    (``event=...``); either way a ``CustomEvent``'s ``detail`` is converted through
    ``to_py()``, so the handler sees a dict or list. An ``async`` handler is scheduled
    rather than dropped — the browser dispatching the event is not waiting on it.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        new_args = list(args)

        for idx in (1, 0):
            if len(new_args) > idx:
                arg = new_args[idx]
                if arg is not None and hasattr(arg, "detail") and not isinstance(arg, PythonEventWrapper):
                    new_args[idx] = PythonEventWrapper(arg)
                    break

        if "event" in kwargs:
            event = kwargs["event"]
            if event is not None and hasattr(event, "detail") and not isinstance(event, PythonEventWrapper):
                kwargs["event"] = PythonEventWrapper(event)

        res = func(*new_args, **kwargs)

        if inspect.iscoroutine(res):
            asyncio.create_task(res)
        return res

    wrapper.__is_py_event__ = True

    return wrapper
