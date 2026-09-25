"""The Python↔JS event boundary, and the page-level events built on it.

Two scales, one subject. At the bottom sits :class:`Listener`: one handler bound to one JS
event target, owning the ``addEventListener`` registration and the ``ffi`` proxy *together* —
two objects with one lifetime that fail silently when released separately. :func:`py_event`
is the same level for template handlers, converting a ``CustomEvent``'s ``detail`` to Python
data and scheduling an ``async`` handler rather than dropping it.

Above that sits the hub: one browser registration per ``(target, event, options)`` serves
every subscriber on the page, so a page with ten shortcuts holds one ``keydown`` listener
rather than ten. Matching, gating and ordering all happen in Python, so what a dormant
subscriber costs is a comparison rather than a Pyodide proxy.

A subscription is a handler *plus a lifetime*. The hub owns the browser registration and
releases it when the last subscriber leaves; the owner — the component or store that
declared the subscription — releases its own on teardown, so an unmounted component and a
hot-swapped one both leave the page as they found it. Handlers run inside one
:func:`~basis.shared.reactive.batch`, so a keystroke that writes three stores costs one
render.

Declarations are class attributes::

    class Sidebar(Component):
        open = False

        @on_key("Escape", when="dismissable")
        def dismiss(self, event):
            event.claim()
            self.open = False

A handler receives a :class:`GlobalEvent` — the event as Python data (``key``, ``mod``,
``in_editable``, …) with ``.native`` as the escape hatch. It is the same wrapper a template
handler gets, plus the typed fields and ``claim()``.

A subscription is the page-scoped twin of a template binding. ``EventBinding`` wires a
handler to one node the component renders (``onclick="{...}"``) and lives as long as that
binding; this module wires a handler to the page itself — a shortcut, a dismissal, a
lifecycle event — and shares one registration between every owner that wants it.

The reactive DAG is where the *values* live, not how the dispatch happens: a gate is a plain
read of the owner's own field or ``@computed``, a handler's writes are ordinary
``ReactiveObject`` writes, and the fan-out runs inside one
:func:`~basis.shared.reactive.batch` so a keystroke that touches three stores costs one
render. Nothing here creates a DAG edge — a subscription is a browser resource with a
lifetime, not a computation.

Client-only in effect, importable everywhere in practice: with no Pyodide there is no
``ffi``, so every listener is inert, no handler runs, and the server imports this module like
any other shared one.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from functools import wraps

from basis.shared.reactive import batch

IS_CLIENT = "pyscript" in sys.modules or "pyodide" in sys.modules

if IS_CLIENT:
    try:
        # type: ignore[reportMissingImports]  # client runtime only
        from pyscript import document, ffi, window
    except ImportError:
        document = ffi = window = None
else:
    document = ffi = window = None


# ──────────────────────────────────────────────
# The boundary: one binding, and the event a handler receives
# ──────────────────────────────────────────────

class Listener:
    """One handler bound to one JS event target. Inert without a browser.

    ``options`` are the browser's own registration options (capture, passive, once); none
    by default, and the capture flag is remembered because unbinding needs it back.
    """

    def __init__(self, target, event: str, handler, options=None):
        self.target = target
        self.event = event
        self.options = options
        # A JS API this browser does not have reads as a falsy value, not as None.
        self.proxy = ffi.create_proxy(handler) if ffi is not None and target else None
        if self.proxy is not None:
            if options is None:
                target.addEventListener(event, self.proxy)
            else:
                target.addEventListener(event, self.proxy, options)

    def detach(self) -> None:
        """Unbind, keeping the proxy alive.

        This is what a one-shot handler calls on itself: unbinding the registration it
        is currently running through is ordinary, freeing the proxy underneath that call
        is not.
        """
        if self.proxy is None:
            return
        self._unbind(self.proxy)

    def dispose(self) -> None:
        """Unbind and free the proxy. Idempotent; call it from outside the handler."""
        proxy = self.proxy
        if proxy is None:
            return
        self.proxy = None
        self._unbind(proxy)
        proxy.destroy()

    def _unbind(self, proxy) -> None:
        """Remove the registration, matching the capture flag it was made with.

        Capture is part of a registration's identity — ``removeEventListener`` only removes
        the one it is told about — so it is passed back. The false case is passed by
        omission, which is the same thing and the form every existing target already takes.
        """
        if isinstance(self.options, dict):
            capture = bool(self.options.get("capture"))
        else:
            capture = bool(self.options)
        if capture:
            self.target.removeEventListener(self.event, proxy, True)
        else:
            self.target.removeEventListener(self.event, proxy)


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

    Idempotent: the wrapper is marked, so wrapping an already-wrapped handler returns
    it rather than stacking a second layer.
    """
    if getattr(func, "__is_py_event__", False):
        return func

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


# ──────────────────────────────────────────────
# The declarations a page-level subscription is made from
# ──────────────────────────────────────────────

#: Instance keys — private, so they bypass the DAG like the rest of the framework's
#: bookkeeping. ``_ATTACHED`` is the idempotency guard for declarations; ``_SUBSCRIBED`` is
#: everything this owner must release, however the subscription was made.
_ATTACHED = "_events_attached"
_SUBSCRIBED = "_event_subscriptions"

#: The input types that accept typing. A key event that lands in one of these is the user
#: writing text; a global shortcut has no business stealing it unless it asked to.
_TEXT_INPUT_TYPES = (
    "", "text", "search", "url", "tel", "email", "password", "number",
    "date", "month", "week", "time", "datetime-local",
)

#: The events that mean the user is typing. Narrow on purpose: a pointerdown inside a text
#: field is an outside-click rather than typing, and a handler that dismisses on one has to
#: see it.
_TYPING_EVENTS = ("keydown", "keyup", "paste", "cut", "input", "beforeinput")

#: The one resync the client entrypoint installs, and the listeners holding it. Page-lifetime
#: client state: the server never reaches them, because ``window`` is None there.
_resync_installed = False
_resync_listeners: list = []


def _as_str(value) -> str:
    """A JS value as a Python string.

    An event property this browser does not have is a falsy JS value rather than ``None``,
    so a key that is not a string reads as the empty string and every comparison against a
    real key stays false.
    """
    return value if isinstance(value, str) else ""


def _resolve_target(target):
    """The JS event target for *target*, or ``None`` without a browser.

    ``"document"`` and ``"window"`` are looked up when the subscriber is created, and a
    callable target is *asked* then too — which is how a declared media query opens its
    ``MediaQueryList`` only when somebody subscribes to it.
    """
    if target == "document":
        return document
    if target == "window":
        return window
    if callable(target):
        return target()
    return target


def _browser_present() -> bool:
    """Whether this process has a document or a window to subscribe to."""
    return document is not None or window is not None


def _options_key(options):
    """Options in a form two registrations can be compared by.

    Capture is part of a registration's identity: a captured and a bubbling listener for
    one event are two different registrations, and ``removeEventListener`` only unbinds
    its own. Keying the hub by the options is what keeps those apart.
    """
    if not options:
        return ()
    if isinstance(options, dict):
        return tuple(sorted((k, bool(v)) for k, v in options.items()))
    return (("capture", bool(options)),)


def _is_editable(target) -> bool:
    """Whether a key event landed in something the user is typing into.

    Content-editable is checked as well as the input types that take text, because that is
    what a code editor's editing surface is — and stealing Escape from an editor is not a
    shortcut, it is a bug.
    """
    if not target:
        return False
    tag = _as_str(getattr(target, "tagName", None)).lower()
    if tag == "textarea":
        return True
    if tag == "input":
        kind = _as_str(getattr(target, "type", None)).lower() or "text"
        return kind in _TEXT_INPUT_TYPES
    return bool(getattr(target, "isContentEditable", False))


class GlobalEvent(PythonEventWrapper):
    """A page event as Python sees it.

    A template handler and a page-level handler receive the browser's event through the same
    wrapper: ``py_event``'s ``PythonEventWrapper``, which converts a ``CustomEvent``'s
    ``detail`` to Python data and hands every unnamed attribute straight through. On top of
    that, this view reads once the fields a global handler usually wants, so no handler has
    to think about the JS boundary — ``key`` is a ``str``, the modifiers are Python bools.
    """

    def __init__(self, native):
        super().__init__(native)
        self.type = _as_str(getattr(native, "type", None))
        self.key = _as_str(getattr(native, "key", None))
        self.code = _as_str(getattr(native, "code", None))
        self.ctrl = bool(getattr(native, "ctrlKey", False))
        self.alt = bool(getattr(native, "altKey", False))
        self.shift = bool(getattr(native, "shiftKey", False))
        self.meta = bool(getattr(native, "metaKey", False))
        self.repeat = bool(getattr(native, "repeat", False))
        self.claimed = False

    @property
    def native(self):
        """The browser's own event — ``target``, ``clipboardData``, ``dataTransfer``, …"""
        return self._original_event

    @property
    def mod(self) -> bool:
        """Meta on macOS, ctrl elsewhere — the platform-agnostic modifier."""
        return self.meta or self.ctrl

    @property
    def in_editable(self) -> bool:
        """Whether this event landed in something the user can type into."""
        if "_in_editable" not in self.__dict__:
            self.__dict__["_in_editable"] = _is_editable(self.target)
        return self.__dict__["_in_editable"]

    @property
    def typing(self) -> bool:
        """Whether this event *is* the user typing: a typing event, in an editable.

        The guard a shortcut is subject to. It is not the same as :attr:`in_editable`,
        which says only what the event landed in.
        """
        return self.type in _TYPING_EVENTS and self.in_editable

    def claim(self) -> None:
        """Handled: stop the dispatch, so no lower-priority subscriber sees this event.

        Claiming is about *our* subscribers, not the browser. An element-level template
        handler has already run by the time a document-level subscriber sees the event, and
        a claimed event still performs its default action.
        """
        self.claimed = True

    def prevent_default(self) -> None:
        """Ask the browser not to perform this event's default action.

        A no-op where the browser refuses to listen: a passive registration — Chromium's
        default for ``wheel``, ``touchstart`` and ``touchmove`` on document/window/body —
        ignores it, which is why a handler that needs it asks for
        ``options={"passive": False}``.
        """
        try:
            self.native.preventDefault()
        except Exception:
            pass


class KeyMatch:
    """A key plus modifiers, matched in Python against the browser's event.

    Matching in Python rather than registering one listener per combo is what lets every
    shortcut on the page share one ``keydown`` registration.

    A named modifier is required. ``ctrl``, ``alt`` and ``meta`` are also *forbidden* when
    unnamed, so ``@on_key("Escape")`` does not fire under Cmd+Escape; ``shift`` is neither
    required nor forbidden unless it is named, because ``event.key`` already reflects it
    (``"?"`` *is* shift+slash). ``mod`` means meta or ctrl.
    """

    def __init__(self, key, *, code=None, mod=False, ctrl=False, alt=False, shift=False,
                 repeat=False):
        self.key = key
        self.code = code
        self.mod = mod
        self.ctrl = ctrl
        self.alt = alt
        self.shift = shift
        self.repeat = repeat

    def matches(self, event) -> bool:
        if event.repeat and not self.repeat:
            return False
        if self.mod:
            if not event.mod:
                return False
        elif event.meta or event.ctrl:
            return False
        if self.ctrl and not event.ctrl:
            return False
        if self.alt:
            if not event.alt:
                return False
        elif event.alt:
            return False
        if self.shift and not event.shift:
            return False
        if self.code is not None:
            return event.code.lower() == self.code.lower()
        return event.key.lower() == self.key.lower()


class Subscription:
    """One handler on one hub entry.

    Idempotent to dispose, and inert without a browser: with no target there is no hub and
    nothing to release. Owners hold these to control their own lifetime — the hub holds the
    registration.
    """

    def __init__(self, hub, handler, *, label="", owner=None, when=None, priority=0,
                 in_editable=False, matcher=None):
        if when is not None:
            if not isinstance(when, str):
                raise TypeError("when= names a reactive attribute; pass a string, not a callable")
            if owner is not None and not hasattr(owner, when):
                raise ValueError(
                    f"when={when!r} is not an attribute of {type(owner).__name__}; a gate "
                    f"names a field or a @computed on the owner"
                )
        self.hub = hub
        self.handler = handler
        self.label = label
        self.owner = owner
        self.when = when
        self.priority = priority
        self.in_editable = in_editable
        self.matcher = matcher
        if hub is not None:
            hub.add(self)

    def dispose(self) -> None:
        """Release this subscriber. Idempotent, and safe from inside its own handler."""
        hub, self.hub = self.hub, None
        if hub is not None:
            hub.release(self)

    def accepts(self, event) -> bool:
        """Whether this subscriber wants this occurrence.

        Cheapest test first: the combo, then the typing guard, then the gate — which reads
        the owner, and may be a computed.
        """
        if self.matcher is not None and not self.matcher.matches(event):
            return False
        if not self.in_editable and event.typing:
            return False
        if self.when is not None:
            gate = getattr(self.owner, self.when, None)
            if not gate:
                return False
        return True

    def call(self, event) -> None:
        """Run the handler. One failing handler is reported, and the rest still run."""
        try:
            self.handler(event)
        except Exception as exc:
            where = self.label or getattr(self.handler, "__qualname__", repr(self.handler))
            print(f"[Basis] {where} failed on '{event.type}': {exc}")

    # The hub's subscriber protocol is ``accepts`` + ``apply``; a Subscription applies by
    # calling its handler.
    def apply(self, event) -> None:
        self.call(event)


class Level:
    """A declared field the browser keeps true while it is true.

    The *level* half of the mechanism — :class:`Subscription` is the *edge* half — and what
    ``media(...)`` and ``key_held(...)`` declare. The hub owns the registration and calls
    :meth:`apply` with every answer that arrives.

    A level never claims, and the typing guard does not apply to it: a field that says "this
    is true" is an observation, not an action competing for a keystroke.
    """

    def __init__(self, hub, owner, name, derive, *, matcher=None, neutral=False, resync=None):
        self.hub = hub
        self.owner = owner
        self.name = name
        self.derive = derive
        self.matcher = matcher
        self.neutral = neutral
        self.read = resync
        if hub is not None:
            hub.add(self)

    def dispose(self) -> None:
        """Release this level. Idempotent, like ``Subscription.dispose``."""
        hub, self.hub = self.hub, None
        if hub is not None:
            hub.release(self)

    def accepts(self, event) -> bool:
        return self.matcher is None or self.matcher.matches(event)

    def apply(self, event) -> None:
        self.write(self.derive(event))

    def resync(self, into=None) -> None:
        """Write what the field should read when no event is arriving: the observation's own
        state where it has one, the neutral where it does not (a ``keyup`` is lost if the
        window blurs first).

        This is the resize an engine does not report, and the back/forward-cache restore.
        """
        value = self.neutral
        if self.read is not None and self.hub is not None:
            value = self.read(self.hub.target)
        self.write(value, into)

    def write(self, value, into=None) -> None:
        """One DAG write, skipped when the value did not move.

        *into* redirects the write — the owner's ``refrain()`` proxy, when a resync is writing
        several levels and wants one flush for all of them.
        """
        value = bool(value)
        if bool(self.owner.__dict__.get(self.name)) != value:
            setattr(into if into is not None else self.owner, self.name, value)


class EventHub:
    """The browser registration for one ``(target, event, options)``, and its subscribers.

    A multiton, like ``MediaQuery``: whoever asks for an observation second gets the first
    one's hub, so the page holds one registration however many owners subscribed — which is
    the whole reason a shortcut costs a comparison instead of a proxy. A hub keeps its
    target alive, which is what keeps its identity key honest.

    ``add``, ``release`` and ``dispatch`` are its whole interface: a subscription uses the
    first two, the registration uses the third.
    """

    _instance_registry: dict = {}

    def __new__(cls, target, event, options=None):
        key = (id(target), event, _options_key(options))
        hub = cls._instance_registry.get(key)
        if hub is None:
            hub = super().__new__(cls)
            cls._instance_registry[key] = hub
        return hub

    def __init__(self, target, event, options=None):
        if "target" in self.__dict__:  # a multiton hit runs __init__ again
            return
        self.target = target
        self.event = event
        self.options = options
        self.key = (id(target), event, _options_key(options))
        self.subscriptions: list[Subscription] = []
        self.listener = None
        self._in_dispatch = False
        self._release_pending = False

    def add(self, subscription: Subscription) -> None:
        self.subscriptions.append(subscription)
        if self.listener is None:
            self.listener = Listener(self.target, self.event, self.dispatch, self.options)

    def release(self, subscription: Subscription) -> None:
        """Drop one subscriber; the last one out releases the browser registration."""
        self.subscriptions = [s for s in self.subscriptions if s is not subscription]
        if self.subscriptions:
            return
        if self._in_dispatch:
            # A handler may be dropping the subscription it is running through. Freeing the
            # proxy underneath that call is exactly what Listener.detach exists to avoid, so
            # the release waits for the dispatch to return.
            self._release_pending = True
            return
        self.close()

    def close(self) -> None:
        """Release the registration, if nobody has subscribed again in the meantime."""
        if self.subscriptions:
            self._release_pending = False
            return
        type(self)._instance_registry.pop(self.key, None)
        listener, self.listener = self.listener, None
        if listener is not None:
            listener.dispose()

    def dispatch(self, native) -> None:
        """Fan one browser event out to the subscribers that want it.

        The registration's sink — the browser calls this, and nothing else does. It works on
        a snapshot, so a subscriber may drop its own subscription, or another's, mid-event
        without disturbing this dispatch.

        Levels run first, whatever their priority: a handler that reads the field has to see
        the value this event just produced. Then handlers, by priority.
        """
        if self.listener is None:
            return  # released mid-event: the registration outlived its subscribers
        event = GlobalEvent(native)
        self._in_dispatch = True
        try:
            with batch():
                for subscriber in sorted(self.subscriptions,
                                         key=lambda s: (not isinstance(s, Level),
                                                        -getattr(s, "priority", 0))):
                    if subscriber.hub is not self:
                        continue  # dropped by an earlier subscriber in this same dispatch
                    if not subscriber.accepts(event):
                        continue
                    subscriber.apply(event)
                    if event.claimed:
                        break
        finally:
            self._in_dispatch = False
            if self._release_pending:
                self._release_pending = False
                self.close()


def subscribe(target, event, handler, *, matcher=None, when=None, priority=0,
              in_editable=False, options=None, owner=None, label=None) -> Subscription:
    """Bind *handler* to *event* on *target*, sharing the registration with every other
    subscriber to the same observation. Returns the subscription.

    The argument order mirrors :class:`Listener`, because this is that same triple with a hub
    in front of it; *target* is ``"document"``, ``"window"``, or any JS event target. This is
    the layer plugins and framework internals use — a component or store wants
    :class:`BrowserMixin` instead, which also records the subscription for its own teardown.

    *when* names a reactive attribute on *owner* (a field or a ``@computed``): the handler
    runs only while it reads truthy. A name that does not resolve is a mistake worth failing
    on, so it raises here rather than never firing in silence.
    """
    if not isinstance(event, str) or not event.strip():
        raise ValueError("subscribe() requires a non-empty event name")
    if not callable(handler):
        raise TypeError(f"subscribe({event!r}) requires a callable handler")

    resolved = _resolve_target(target)
    if resolved is None:
        # No browser: the declaration is inert, and dispose() on the inert subscription is
        # safe for the caller that always calls it.
        return Subscription(None, handler, label=label or "", owner=owner, when=when,
                            priority=priority, in_editable=in_editable, matcher=matcher)

    hub = EventHub(resolved, event, options)
    return Subscription(
        hub, handler,
        label=label or getattr(handler, "__qualname__", ""),
        owner=owner, when=when, priority=priority, in_editable=in_editable, matcher=matcher,
    )


# ──────────────────────────────────────────────
# Declarations
# ──────────────────────────────────────────────

class Declaration:
    """One observation an owner asked for, before there is an owner to attach it to.

    A declaration is either an **edge** (a handler: call this method when the browser
    dispatches) or a **level** (a field: write this attribute while it is true). Same
    observation, two things done with the answer.
    """

    __slots__ = ("event", "target", "when", "priority", "in_editable", "options", "matcher",
                 "kind", "derive", "neutral", "resync")

    def __init__(self, event, *, target="document", when=None, priority=0, in_editable=False,
                 options=None, matcher=None, kind="handler", derive=None, neutral=False,
                 resync=None):
        self.event = event
        self.target = target
        self.when = when
        self.priority = priority
        self.in_editable = in_editable
        self.options = options
        self.matcher = matcher
        self.kind = kind
        #: A level's value for one event, and what the server ships before the browser answers.
        self.derive = derive
        self.neutral = neutral
        #: A level's re-read: ``(target) -> value``, for the moments no event arrives.
        self.resync = resync


def _declare(func, declaration):
    """Mark a method as a subscriber. The declarations travel on the function — the
    ``@computed`` idiom — so nothing is registered at import time, and nothing is registered
    on the server: the method becomes a subscriber when its owner is live.

    They accumulate rather than replace, because one handler may answer more than one
    observation (``@on_key("K")`` stacked over ``@on_key("P")``).
    """
    func.__dict__.setdefault("__event_declarations__", []).append(declaration)
    return func


def on_global(event, *, target="document", when=None, priority=0, in_editable=False,
              options=None, matcher=None):
    """Declare a handler for *event* on *target* (``"document"`` or ``"window"``)."""
    def decorate(func):
        return _declare(func, Declaration(
            event, target=target, when=when, priority=priority,
            in_editable=in_editable, options=options, matcher=matcher,
        ))
    return decorate


def on_document(event, **kwargs):
    """Declare a handler for a document-level event."""
    return on_global(event, **kwargs)


def on_window(event, **kwargs):
    """Declare a handler for a window-level event."""
    return on_global(event, target="window", **kwargs)


def on_key(combo, *, phase="down", code=None, mod=False, ctrl=False, alt=False,
           shift=False, repeat=False, **kwargs):
    """Declare a keyboard handler for *combo* — matched in Python, on ``keydown`` by
    default.

    *combo* is ``event.key`` (``"Escape"``, ``"k"``, ``"?"``), matched case-insensitively;
    *code* matches ``event.code`` instead, for a binding that follows the physical key.
    *phase* picks ``keydown`` or ``keyup``; a key held down is ignored unless *repeat* asks
    for it. See :class:`KeyMatch` for how the modifiers are required and forbidden.
    """
    if phase not in ("down", "up"):
        raise ValueError(f"on_key(phase={phase!r}) takes 'down' or 'up'")
    if not isinstance(combo, str) or not combo.strip():
        raise ValueError("on_key() requires a key name, e.g. on_key('Escape')")
    matcher = KeyMatch(combo, code=code, mod=mod, ctrl=ctrl, alt=alt, shift=shift,
                       repeat=repeat)

    def decorate(func):
        return _declare(func, Declaration(
            "keyup" if phase == "up" else "keydown", matcher=matcher, **kwargs
        ))
    return decorate


def declared_declarations(cls) -> dict:
    """Every declaration in effect for *cls*: base-first, so an override wins.

    Two kinds of source, one map. A decorated method carries its declarations on the function
    (the ``@computed`` idiom); a field declaration is a descriptor that says which
    observations feed it (``media(...)``, ``key_held(...)``). Both are keyed by attribute name
    — which, for a level, is also the field it writes.

    A name maps to a tuple: a handler may answer several observations (``@on_key("K")``
    stacked over ``@on_key("P")``), and a level usually needs several (a held key is a
    ``keydown``, a ``keyup``, and the two ways of losing focus). A name overridden *without* a
    declaration withdraws the inherited one: the subclass's member is what would run.
    """
    declared: dict = {}
    for klass in reversed(cls.__mro__):
        for name, member in klass.__dict__.items():
            if isinstance(member, LevelDeclaration):
                declarations = tuple(member.declarations())
            else:
                declarations = tuple(getattr(_unwrap(member), "__event_declarations__", ()) or ())
            if declarations:
                declared[name] = declarations
            elif name in declared:
                del declared[name]
    return declared


def _unwrap(member):
    """The plain function behind a descriptor, so a decorated method is recognised."""
    for attr in ("__func__", "fget"):
        inner = getattr(member, attr, None)
        if inner is not None:
            return inner
    return member


class LevelDeclaration:
    """A class attribute declaring a field the browser keeps up to date.

    Declaration only. The owner's mixin materialises the neutral, attaches the observations
    and releases them; ``__get__`` without ``__set__`` is what makes that work — the instance
    dict shadows this attribute from the first write on, leaving reads, writes, serialisation
    and hydration on the ordinary path.
    """

    def __init__(self, neutral=False):
        self.neutral = bool(neutral)

    def declarations(self) -> tuple:
        """The observations that feed this field, as :class:`Declaration` objects."""
        raise NotImplementedError

    def __get__(self, instance, owner=None):
        # Reachable only before materialisation (class introspection, or an owner that never
        # got that far). One instance may serve several declaration sites, so the attribute
        # name is not knowable from here — the neutral keeps the read total.
        if instance is None:
            return self
        return self.neutral


class EventField(LevelDeclaration):
    """A level fed by identified browser events — ``key_held(...)``, ``pointer_held()``, …"""

    def __init__(self, observations, *, neutral=False):
        super().__init__(neutral)
        self.observations = tuple(observations)

    def declarations(self) -> tuple:
        return self.observations


def _pressed(event):
    """The key or button went down."""
    return True


def _released(event):
    """The key or button came up — or the window stopped listening before it did."""
    return False


def _hidden(event):
    """``visibilityState`` lives on the document, not on the event."""
    return _as_str(getattr(document, "visibilityState", None)).lower() == "hidden"


def key_held(combo, *, code=None, mod=False, ctrl=False, alt=False, shift=False):
    """Declare a field that reads true while *combo* is held down.

    The release is not only ``keyup``: a key held while the window loses focus never delivers
    one, so ``blur`` and ``pagehide`` write the neutral too.
    """
    matcher = KeyMatch(combo, code=code, mod=mod, ctrl=ctrl, alt=alt, shift=shift)
    return EventField((
        Declaration("keydown", kind="level", matcher=matcher, derive=_pressed),
        Declaration("keyup", kind="level", matcher=matcher, derive=_released),
        Declaration("blur", target="window", kind="level", derive=_released),
        Declaration("pagehide", target="window", kind="level", derive=_released),
    ))


def pointer_held():
    """Declare a field that reads true while a pointer button is down."""
    return EventField((
        Declaration("pointerdown", kind="level", derive=_pressed),
        Declaration("pointerup", kind="level", derive=_released),
        Declaration("pointercancel", kind="level", derive=_released),
        Declaration("blur", target="window", kind="level", derive=_released),
    ))


def document_hidden():
    """Declare a field that reads true while the document is hidden — tab switched away."""
    return EventField((
        Declaration("visibilitychange", kind="level", derive=_hidden),
    ))


class BrowserMixin:
    """What this object declares about the browser: levels to read, edges to react to.

    One declaration map, one attach pass, one release list — a media query and a page event are
    the same lifecycle, differing only in what the answer is used for.

    The lifecycle calls are explicit rather than lifecycle-hook overrides: a component attaches
    at the end of ``initialize()`` and releases in ``_teardown_bindings()``; a store attaches in
    ``on_client_ready()`` and releases in ``on_client_teardown()`` — the two hooks below are the
    store's half, and an override calls ``super()``.
    """

    def on_global(self, event, handler, *, target="document", when=None, priority=0,
                  in_editable=False, options=None) -> Subscription:
        """Bind *handler* to a page-level *event*, owned by this instance.

        The imperative form. The subscription is recorded for this owner's teardown, so a
        component that unmounts — or is hot-swapped — leaves nothing bound.
        """
        return self._record(subscribe(
            target, event, handler, when=when, priority=priority,
            in_editable=in_editable, options=options, owner=self,
            label=f"{type(self).__name__}.{getattr(handler, '__name__', 'handler')}",
        ))

    def _record(self, subscriber):
        """Remember a subscriber, so this owner's teardown releases it however it was made —
        declared or imperative."""
        self.__dict__.setdefault(_SUBSCRIBED, []).append(subscriber)
        return subscriber

    def _attach_declarations(self) -> None:
        """Attach every declaration in effect for this class. Idempotent."""
        declared = declared_declarations(type(self))
        if not declared or not _browser_present():
            return
        attached = self.__dict__.setdefault(_ATTACHED, {})
        for name, declarations in declared.items():
            if name in attached:
                continue
            handler = getattr(self, name, None)
            attached[name] = [
                self._attach_one(name, declaration, handler)
                for declaration in declarations
                if _resolve_target(declaration.target) is not None
            ]
        # A level's field is only correct once read: attaching subscribes, it does not tell us
        # the answer. This is also what corrects a stale value on a bfcache restore.
        self._resync_levels()

    def _attach_one(self, name, declaration, handler):
        """One declaration, attached: a level writes the field, an edge calls the handler."""
        hub = EventHub(_resolve_target(declaration.target), declaration.event,
                       declaration.options)
        if declaration.kind == "level":
            return self._record(Level(
                hub, self, name, declaration.derive,
                matcher=declaration.matcher, neutral=declaration.neutral,
                resync=declaration.resync,
            ))
        return self._record(Subscription(
            hub, handler, label=f"{type(self).__name__}.{name}", owner=self,
            when=declaration.when, priority=declaration.priority,
            in_editable=declaration.in_editable, matcher=declaration.matcher,
        ))

    def _detach_declarations(self) -> None:
        """Release every subscriber this owner created. Safe to call repeatedly."""
        for subscriber in self.__dict__.pop(_SUBSCRIBED, []):
            subscriber.dispose()
        self.__dict__.pop(_ATTACHED, None)

    def _resync_levels(self) -> None:
        """Re-read every attached level: the resize an engine does not report, and the restore
        from the back/forward cache.

        One ``refrain()`` gives one flush however many levels moved, and it skips the ones that
        did not.
        """
        levels = [subscriber
                  for subscribers in (self.__dict__.get(_ATTACHED) or {}).values()
                  for subscriber in subscribers
                  if isinstance(subscriber, Level)]
        if not levels:
            return
        with self.refrain() as batched:
            for level in levels:
                level.resync(batched)

    def on_client_ready(self) -> None:
        """Client-only: the document has mounted. Attaching here rather than at construction is
        what keeps a subscriber's first write an ordinary DAG update. Overriders must call
        ``super().on_client_ready()``."""
        self._attach_declarations()

    def on_client_teardown(self) -> None:
        """Client-only: undo :meth:`on_client_ready`. Safe to call repeatedly."""
        self._detach_declarations()


def install_resync(registry) -> None:
    """Register one shared resync over *registry*. Client-only, idempotent.

    A level's own event is the mechanism; this covers the cases where none arrives — an engine
    that does not fire ``change`` while the viewport is dragged, and a document restored from
    the back/forward cache with stale values.
    """
    global _resync_installed
    if _resync_installed or window is None:
        return
    _resync_installed = True
    for event_name in ("resize", "orientationchange", "pageshow"):
        # Held for the page lifetime: the client never releases these.
        _resync_listeners.append(
            Listener(window, event_name, lambda event=None: _resync_all(registry))
        )


def _resync_all(registry) -> None:
    for store in list(registry.values()):
        store._resync_levels()
