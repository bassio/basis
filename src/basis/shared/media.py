"""Named CSS media queries as reactive ``Store`` fields.

``media()`` declares a query on a class attribute of any ``Store`` subclass::

    class LayoutStore(Store):
        narrow = media("(width <= 600px)")
        hover = media("(hover: hover)", default=True)

The store materialises a real boolean field under that name, so from then on it
serialises, hydrates, and reacts like any other field — ``$layout.narrow`` in a
template, or a ``@computed`` reading ``self.narrow``.

Only the browser can evaluate a query, so ``default`` is the neutral the server and the
client agree on: server-rendered markup and the client's first paint match, and the
first listener write is an ordinary DAG update. Declaring the same query string twice
hands back the same :class:`MediaQuery`, so the page holds one ``MediaQueryList`` and one
``change`` listener per distinct query however many stores ask about it.
"""

import sys

from basis.shared.js import Listener

IS_CLIENT = "pyscript" in sys.modules or "pyodide" in sys.modules

if IS_CLIENT:
    try:
        from pyscript import window
    except ImportError:
        window = None
else:
    window = None

_DECLARED = "__media_declared__"
_HANDLES = "_media_handles"

# The one resync the client entrypoint installs. Page-lifetime client state: the
# server never reaches it, because ``window`` is None there.
_resync_installed = False
_resync_listeners: list[Listener] = []


def media(query: str, *, default: bool = False) -> "MediaQuery":
    """Declare *query* as a reactive field on a ``Store`` subclass.

    *default* is the neutral both sides agree on before the browser is asked: the value
    true of the widest range of clients. ``False`` suits a width query; ``(hover:
    hover)`` wants ``True`` so a desktop render is already correct and touch is a
    client-only correction.
    """
    if not isinstance(query, str) or not query.strip():
        raise ValueError("media() requires a non-empty media query string")
    return MediaQuery(query.strip(), bool(default))


class MediaQuery:
    """A declared media query — one instance per distinct query string.

    Declaration and browser object are the same thing, which is what makes the sharing
    fall out for free: whoever declares the string second gets the first one's instance,
    so the page never holds two ``MediaQueryList``s for one query.

    It holds no value of its own. The declaring store materialises a real field under
    the attribute name, and because this defines ``__get__`` without ``__set__`` the
    instance dict shadows the class attribute from then on, leaving reads, writes,
    serialisation, and hydration on the ordinary path.
    """

    _instance_registry = {}  # query string -> MediaQuery

    def __new__(cls, query: str, default: bool = False):
        existing = cls._instance_registry.get(query)
        if existing is not None:
            if existing.default is not default:
                raise ValueError(
                    f"media({query!r}) was already declared with "
                    f"default={existing.default!r}; one query has one neutral, because "
                    "the server and the client both render it before the browser "
                    "answers."
                )
            return existing
        instance = super().__new__(cls)
        cls._instance_registry[query] = instance
        return instance

    def __init__(self, query: str, default: bool = False):
        if "query" in self.__dict__:  # a multiton hit runs __init__ again
            return
        self.query = query
        self.default = default
        self.mql = None
        self.listener = None
        self.targets = []

    def __set_name__(self, owner, name):
        declared = owner.__dict__.get(_DECLARED)
        if declared is None:
            # Own dict only: a subclass must never append to a parent's map.
            declared = {}
            setattr(owner, _DECLARED, declared)
        declared[name] = self

    def __get__(self, instance, owner=None):
        # Reachable only before materialisation (class introspection, or a store that
        # never got that far). One instance serves every declaration site, so the
        # attribute name is not knowable from here — the neutral keeps the read total.
        if instance is None:
            return self
        return self.default

    @property
    def matches(self) -> bool:
        """The browser's answer, or the neutral while nothing has asked yet."""
        if self.mql is None:
            return self.default
        # bool() normalises a JS boolean crossing the Pyodide boundary.
        return bool(self.mql.matches)

    def add_target(self, instance, name: str) -> None:
        """Record a field this query answers. Idempotent."""
        for target_instance, target_name in self.targets:
            if target_instance is instance and target_name == name:
                return
        self.targets.append((instance, name))
        self._listen()

    def remove_target(self, instance) -> None:
        """Drop one owner's claims; the last one out releases the browser listener."""
        self.targets = [t for t in self.targets if t[0] is not instance]
        if not self.targets:
            self._close()

    def _listen(self) -> None:
        """Create the browser object and its ``change`` listener, once per query."""
        if self.listener is not None or window is None:
            return
        self.mql = window.matchMedia(self.query)
        self.listener = Listener(self.mql, "change", self._on_change)

    def _close(self) -> None:
        """Release the listener. The instance stays registered as the declaration."""
        if self.listener is None:
            return
        self.listener.dispose()
        self.mql = None
        self.listener = None

    def _on_change(self, event) -> None:
        live = bool(event.matches)
        for instance, name in self.targets:
            # A redundant write would dirty the graph for no reason.
            if instance.__dict__.get(name) != live:
                setattr(instance, name, live)


class MediaMixin:
    """Wires ``media()`` declarations into the client lifecycle of their owner.

    Sits in :class:`~basis.shared.store.Store`'s MRO, so every store gets it; nothing
    here is store-specific beyond reading ``__dict__`` and the DAG. A subclass that
    overrides ``on_client_ready`` or ``on_client_teardown`` must call ``super()`` to
    keep its declared queries attached.
    """

    @classmethod
    def declared_media(cls) -> dict:
        """The declarations in effect for *cls*: base-first, so an override wins."""
        merged = {}
        for klass in reversed(cls.__mro__):
            merged.update(klass.__dict__.get(_DECLARED) or {})
        return merged

    def on_client_ready(self) -> None:
        """Client-only: the document has mounted; attach client-side listeners here."""
        self._attach_media()

    def on_client_teardown(self) -> None:
        """Client-only: undo :meth:`on_client_ready`. Safe to call repeatedly."""
        self._detach_media()

    def _materialize_media(self) -> None:
        """Give every declared query a real field, so it serialises and hydrates.

        Guarded on absence rather than on hydration: a field the server did not ship is
        still created, so a declaration skew between the two sides cannot leave a query
        without a field.
        """
        for name, query in type(self).declared_media().items():
            if name not in self.__dict__:
                setattr(self, name, query.default)

    def _attach_media(self) -> None:
        """Attach the declared queries to their shared handlers. Idempotent."""
        declared = type(self).declared_media()
        if window is None or not declared:
            return
        handles = self.__dict__.setdefault(_HANDLES, {})
        for name, query in declared.items():
            query.add_target(self, name)
            handles[name] = query
        self._resync_media()

    def _detach_media(self) -> None:
        """Undo :meth:`_attach_media`. Safe to call more than once."""
        handles = self.__dict__.pop(_HANDLES, None)
        if not handles:
            return
        for query in set(handles.values()):
            query.remove_target(self)

    def _resync_media(self) -> None:
        """Re-read every attached query and push the answers through the DAG.

        One ``refrain()`` gives one flush, and ``Refrain`` skips unchanged values, so a
        re-read that moves nothing re-renders nothing.
        """
        handles = self.__dict__.get(_HANDLES)
        if not handles:
            return
        with self.refrain() as batched:
            for name, query in handles.items():
                setattr(batched, name, query.matches)


def install_media_resync(registry) -> None:
    """Register one shared resize resync over *registry*. Client-only, idempotent.

    A per-query ``change`` listener is the mechanism; this covers a size query on an
    engine that does not fire ``change`` while the viewport is being dragged.
    """
    global _resync_installed
    if _resync_installed or window is None:
        return
    _resync_installed = True
    for event_name in ("resize", "orientationchange"):
        # Held for the page lifetime: the client never releases these.
        _resync_listeners.append(
            Listener(window, event_name, lambda event=None: _resync_all(registry))
        )


def _resync_all(registry) -> None:
    for store in list(registry.values()):
        store._resync_media()
