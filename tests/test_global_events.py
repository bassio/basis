"""Tests for ``basis.shared.events`` — the page-level event hub.

The client path runs against a fake document and a fake ``ffi``, because these tests execute
server-side where the real ones are absent. What the hub owes its callers is asserted
directly: one registration however many subscribers, priority order, the gate, the typing
guard, and a registration released when the last subscriber leaves.
"""

import pytest

from basis.shared import events as events_module
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.events import (EventHub, KeyMatch, PythonEventWrapper, declared_declarations,
                                  document_hidden, key_held, on_global, on_key, pointer_held,
                                  subscribe)
from basis.shared.reactive import computed
from basis.shared.store import Store
from js_fakes import FakeFFI


class FakeEvent:
    """A browser event: the properties a handler may read, and ``preventDefault``."""

    def __init__(self, type, *, key=None, code=None, target=None, ctrl=False, alt=False,
                 shift=False, meta=False, repeat=False, detail=None):
        self.type = type
        self.key = key
        self.code = code
        self.target = target
        self.ctrlKey = ctrl
        self.altKey = alt
        self.shiftKey = shift
        self.metaKey = meta
        self.repeat = repeat
        self.detail = detail
        self.default_prevented = False

    def preventDefault(self):
        self.default_prevented = True


class FakeDetail:
    """A JS object crossing the boundary: ``to_py`` is the conversion Pyodide offers."""

    def __init__(self, data):
        self.data = data

    def to_py(self):
        return self.data


class FakeElement:
    """The element an event landed in — enough for the typing guard."""

    def __init__(self, tag="div", type="text", content_editable=False):
        self.tagName = tag.upper()
        self.type = type
        self.isContentEditable = content_editable


class FakeTarget:
    """A JS event target: the registrations the browser would hold, as the browser holds
    them (event, proxy, options)."""

    def __init__(self, name="document"):
        self.name = name
        self.listeners = []
        self.removed = []

    def addEventListener(self, event, proxy, options=None):
        self.listeners.append((event, proxy, options))

    def removeEventListener(self, event, proxy, capture=False):
        self.removed.append((event, proxy, capture))
        self.listeners = [row for row in self.listeners if row[:2] != (event, proxy)]

    def dispatch(self, event, **fields):
        """Deliver one event to everything registered, as the browser would."""
        delivered = 0
        for name, proxy, _options in list(self.listeners):
            if name == event:
                proxy(FakeEvent(event, **fields))
                delivered += 1
        return delivered

    def events(self):
        return [name for name, _proxy, _options in self.listeners]


@pytest.fixture
def fake_browser(monkeypatch):
    """A client: a fake document, a fake ``ffi``, and no hubs left over.

    The hub registry is keyed by the target's identity, so a target from an earlier test
    must not be reachable through a recycled ``id``.
    """
    document = FakeTarget("document")
    monkeypatch.setattr(events_module, "document", document)
    monkeypatch.setattr(events_module, "window", FakeTarget("window"))
    EventHub._instance_registry.clear()
    monkeypatch.setattr(events_module, "ffi", FakeFFI())
    yield document
    EventHub._instance_registry.clear()


@pytest.fixture(autouse=True)
def _clean_store_registries():
    """A name or config reused across tests trips the store conflict guards."""
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()


class Owner:
    """A plain owner: the gate and the identity a subscription needs, nothing else."""

    def __init__(self):
        self.open = False


class Escapable(Owner):
    def __init__(self):
        super().__init__()
        self.seen = []

    @on_global("keydown", when="open")
    def handler(self, event):
        self.seen.append(event.key)


# ── Sharing ────────────────────────────────────────────────────────────────────

def test_one_registration_serves_every_subscriber(fake_browser):
    """Three subscribers on one key are one listener: that sharing is the point."""
    for _ in range(3):
        subscribe("document", "keydown", lambda event: None)

    assert fake_browser.events() == ["keydown"]


def test_the_hub_is_a_multiton_per_observation(fake_browser):
    """The registry lives on the class, as ``MediaQuery``'s does: one hub per observation."""
    first = subscribe("document", "keydown", lambda event: None)
    second = subscribe("document", "keydown", lambda event: None)

    assert first.hub is second.hub
    assert list(EventHub._instance_registry) == [(id(fake_browser), "keydown", ())]

    second.dispose()
    assert len(EventHub._instance_registry) == 1  # one subscriber left

    first.dispose()
    assert EventHub._instance_registry == {}


def test_a_global_event_is_the_wrapper_template_handlers_get(fake_browser):
    """One event view for both paths: the page hub and ``py_event`` share the wrapper."""
    from basis.shared.events import PythonEventWrapper

    seen = []
    subscribe("document", "keydown", seen.append)

    fake_browser.dispatch("keydown", key="Escape", detail=FakeDetail({"tag": "x"}))

    assert isinstance(seen[0], PythonEventWrapper)
    assert seen[0].key == "Escape"
    assert seen[0].detail == {"tag": "x"}
    assert seen[0].target is None


def test_subscribers_to_different_targets_do_not_share(fake_browser):
    subscribe("document", "keydown", lambda event: None)
    subscribe("window", "keydown", lambda event: None)

    assert fake_browser.events() == ["keydown"]
    assert events_module.window.events() == ["keydown"]


def test_options_are_part_of_the_registration(fake_browser):
    """Capture is part of a registration's identity, and removal has to match it."""
    plain = subscribe("document", "wheel", lambda event: None, options={"passive": False})
    captured = subscribe("document", "wheel", lambda event: None, options={"capture": True})

    assert len(fake_browser.listeners) == 2  # two registrations, so two hubs
    assert fake_browser.listeners[0][2] == {"passive": False}

    captured.dispose()
    assert fake_browser.removed[-1][2] is True
    assert fake_browser.events() == ["wheel"]  # the bubbling registration stays

    plain.dispose()
    assert fake_browser.removed[-1][2] is False


# ── Order and claim ────────────────────────────────────────────────────────────

def test_priority_orders_the_dispatch_and_a_claim_stops_it(fake_browser):
    seen = []
    subscribe("document", "keydown", lambda event: seen.append("low"), priority=0)
    subscribe("document", "keydown", lambda event: seen.append("high") or event.claim(),
              priority=10)
    subscribe("document", "keydown", lambda event: seen.append("last"))

    fake_browser.dispatch("keydown", key="Escape")

    assert seen == ["high"]


def test_equally_prioritised_subscribers_run_in_registration_order(fake_browser):
    seen = []
    for name in ("first", "second", "third"):
        subscribe("document", "keydown", lambda event, name=name: seen.append(name))

    fake_browser.dispatch("keydown", key="Escape")

    assert seen == ["first", "second", "third"]


def test_a_failing_handler_does_not_stop_the_rest(fake_browser, capsys):
    seen = []

    def boom(event):
        raise RuntimeError("boom")

    subscribe("document", "keydown", boom)
    subscribe("document", "keydown", lambda event: seen.append("ran"))

    fake_browser.dispatch("keydown", key="Escape")

    assert seen == ["ran"]
    assert "boom" in capsys.readouterr().out


def test_prevent_default_is_the_handlers_call(fake_browser):
    """Claiming stops our dispatch; it says nothing about the browser's default."""
    observed = []

    def claim_only(event):
        event.claim()

    subscribe("document", "keydown", claim_only)
    subscribe("document", "keydown", lambda event: observed.append(event.default_prevented))

    fake_browser.dispatch("keydown", key="Escape")

    assert observed == []  # claimed, so the second handler never ran


def test_a_handler_can_ask_the_browser_to_stand_down(fake_browser):
    observed = []
    subscribe("document", "keydown", lambda event: event.prevent_default())
    subscribe("document", "keydown", lambda event: observed.append(event.default_prevented))

    fake_browser.dispatch("keydown", key="Escape")

    assert observed == [True]


# ── The gate ───────────────────────────────────────────────────────────────────

def test_a_falsy_gate_suppresses_the_handler_but_not_the_registration(fake_browser):
    owner = Escapable()
    subscribe("document", "keydown", owner.handler, when="open", owner=owner)

    fake_browser.dispatch("keydown", key="Escape")
    assert owner.seen == []
    assert fake_browser.events() == ["keydown"]  # still bound, just not interested

    owner.open = True
    fake_browser.dispatch("keydown", key="Escape")
    assert owner.seen == ["Escape"]


def test_a_gate_that_names_nothing_is_a_mistake_worth_failing_on(fake_browser):
    with pytest.raises(ValueError):
        subscribe("document", "keydown", lambda event: None, when="openned",
                  owner=Escapable())


def test_a_gate_may_be_a_computed(fake_browser):
    class Gated(Owner):
        locked = True

        @computed
        def dismissable(self):
            return self.open and not self.locked

    owner = Gated()
    seen = []
    subscribe("document", "keydown", lambda event: seen.append("ran"), when="dismissable",
              owner=owner)

    owner.open = True
    fake_browser.dispatch("keydown", key="Escape")
    assert seen == []

    owner.locked = False
    fake_browser.dispatch("keydown", key="Escape")
    assert seen == ["ran"]


# ── Keys ───────────────────────────────────────────────────────────────────────

def test_a_combo_requires_its_modifiers(fake_browser):
    seen = []
    subscribe("document", "keydown", lambda event: seen.append(event.key))
    subscribe("document", "keydown", lambda event: seen.append("mod+K"),
              matcher=KeyMatch("K", mod=True))

    fake_browser.dispatch("keydown", key="k", ctrl=True)
    fake_browser.dispatch("keydown", key="k", meta=True)

    assert seen == ["k", "mod+K", "k", "mod+K"]


def test_a_plain_key_does_not_fire_under_a_command_modifier(fake_browser):
    seen = []
    subscribe("document", "keydown", lambda event: seen.append(event.key),
              matcher=KeyMatch("Escape"))

    fake_browser.dispatch("keydown", key="Escape", ctrl=True)
    assert seen == []

    fake_browser.dispatch("keydown", key="Escape")
    assert seen == ["Escape"]


def test_shift_is_left_to_the_key_itself(fake_browser):
    """``?`` is shift+slash: requiring shift to be unheld would make it unreachable."""
    seen = []
    subscribe("document", "keydown", lambda event: seen.append(event.key),
              matcher=KeyMatch("?"))

    fake_browser.dispatch("keydown", key="?", shift=True)

    assert seen == ["?"]


def test_a_held_key_is_ignored_unless_asked_for(fake_browser):
    seen = []
    subscribe("document", "keydown", lambda event: seen.append("plain"),
              matcher=KeyMatch("Escape"))
    subscribe("document", "keydown", lambda event: seen.append("repeat"),
              matcher=KeyMatch("Escape", repeat=True))

    fake_browser.dispatch("keydown", key="Escape", repeat=True)

    assert seen == ["repeat"]


def test_matching_can_follow_the_physical_key(fake_browser):
    seen = []
    subscribe("document", "keydown", lambda event: seen.append(1),
              matcher=KeyMatch("k", code="KeyK"))

    fake_browser.dispatch("keydown", key="Unidentified", code="KeyK")
    assert seen == [1]

    fake_browser.dispatch("keydown", key="k", code="KeyX")
    assert seen == [1]


def test_keyup_is_a_different_event(fake_browser):
    class Combo(Owner):
        @on_key("Escape", phase="up")
        def release(self, event):
            pass

    assert declared_declarations(Combo)["release"][0].event == "keyup"


# ── Typing ─────────────────────────────────────────────────────────────────────

def test_typing_in_an_editor_is_left_alone_unless_asked(fake_browser):
    editor = FakeElement(tag="div", content_editable=True)
    field = FakeElement(tag="input", type="text")
    checkbox = FakeElement(tag="input", type="checkbox")
    seen = []
    subscribe("document", "keydown", lambda event: seen.append("plain"),
              matcher=KeyMatch("Escape"))
    subscribe("document", "keydown", lambda event: seen.append("asked"), in_editable=True,
              matcher=KeyMatch("Escape"))

    fake_browser.dispatch("keydown", key="Escape", target=editor)
    fake_browser.dispatch("keydown", key="Escape", target=field)
    fake_browser.dispatch("keydown", key="Escape", target=checkbox)
    fake_browser.dispatch("keydown", key="Escape", target=None)

    assert seen == ["asked", "asked", "plain", "asked", "plain", "asked"]


def test_an_outside_click_in_a_field_is_not_typing(fake_browser):
    """The guard is for typing events: a dismissal handler has to see a pointerdown."""
    seen = []
    subscribe("document", "pointerdown", lambda event: seen.append("outside"))

    fake_browser.dispatch("pointerdown", target=FakeElement(tag="input", type="text"))

    assert seen == ["outside"]


# ── Lifetime ───────────────────────────────────────────────────────────────────

def test_the_last_subscriber_out_releases_the_registration(fake_browser):
    ffi = events_module.ffi
    first = subscribe("document", "keydown", lambda event: None)
    second = subscribe("document", "keydown", lambda event: None)

    first.dispose()
    assert fake_browser.events() == ["keydown"]  # one left: the registration stays
    assert ffi.destroyed == []

    second.dispose()
    assert fake_browser.events() == []
    assert [row[0] for row in fake_browser.removed] == ["keydown"]
    assert len(ffi.destroyed) == 1
    assert EventHub._instance_registry == {}


def test_dispose_is_idempotent(fake_browser):
    subscription = subscribe("document", "keydown", lambda event: None)
    subscription.dispose()
    subscription.dispose()

    assert len(fake_browser.removed) == 1


def test_a_handler_may_drop_the_subscription_it_is_running_through(fake_browser):
    """The proxy must outlive its own call: the release waits for the dispatch to return."""
    seen = []

    def once(event):
        seen.append("ran")
        subscription.dispose()

    subscription = subscribe("document", "keydown", once)

    fake_browser.dispatch("keydown", key="Escape")

    assert seen == ["ran"]
    assert fake_browser.events() == []
    assert len(events_module.ffi.destroyed) == 1


def test_a_subscription_added_mid_dispatch_survives_it(fake_browser):
    """The release is 'last one out', not 'the first handler that emptied the list'."""
    added = []

    def add_one(event):
        added.append(subscribe("document", "keydown", lambda e: None))

    subscribe("document", "keydown", add_one)

    fake_browser.dispatch("keydown", key="Escape")

    assert len(added) == 1
    assert fake_browser.events() == ["keydown"]
    assert EventHub._instance_registry  # not retired: someone is still subscribed


def test_nothing_is_registered_without_a_browser(monkeypatch):
    monkeypatch.setattr(events_module, "document", None)
    monkeypatch.setattr(events_module, "window", None)

    subscription = subscribe("document", "keydown", lambda event: None)

    assert subscription.hub is None
    subscription.dispose()  # safe for the caller that always calls it
    assert EventHub._instance_registry == {}


# ── Lifecycle ──────────────────────────────────────────────────────────────────

def test_a_component_attaches_on_mount_and_releases_on_destroy(fake_browser):
    class Drawer(Component):
        __tag__ = "x-events-drawer"
        open = False
        dismissed = 0

        @on_key("Escape", when="open")
        def dismiss(self, event):
            self.dismissed += 1
            self.open = False

        def template(self):
            """<div class="drawer"></div>"""

    drawer = Drawer.mount(Element("div", attrs={}, children=[]))
    assert fake_browser.events() == ["keydown"]

    fake_browser.dispatch("keydown", key="Escape")  # closed: the gate holds it off
    assert drawer.dismissed == 0

    drawer.open = True
    fake_browser.dispatch("keydown", key="Escape")
    assert drawer.dismissed == 1
    assert drawer.open is False

    drawer.destroy()
    assert fake_browser.events() == []
    assert len(events_module.ffi.destroyed) == 1


def test_a_store_attaches_when_the_client_is_ready_and_releases_on_teardown(fake_browser):
    class UiStore(Store):
        palette_open = False

        @on_key("K", mod=True)
        def toggle_palette(self, event):
            event.claim()
            self.palette_open = not self.palette_open

    store = UiStore("test_events_ui")
    assert fake_browser.events() == []  # not live until the document has mounted

    store.on_client_ready()
    assert fake_browser.events() == ["keydown"]

    fake_browser.dispatch("keydown", key="k", ctrl=True)
    assert store.palette_open is True

    store.on_client_teardown()
    assert fake_browser.events() == []

    store.on_client_ready()  # a bfcache restore attaches again, once
    assert fake_browser.events() == ["keydown"]
    assert len(events_module.ffi.created) == 2


def test_an_imperative_subscription_is_released_with_its_owner(fake_browser):
    class Watcher(Component):
        __tag__ = "x-events-watcher"
        hidden = False

        def on_mounted(self):
            self.on_global("visibilitychange", self._on_hidden, when="hidden")

        def _on_hidden(self, event):
            pass

        def template(self):
            """<div class="watcher"></div>"""

    watcher = Watcher.mount(Element("div", attrs={}, children=[]))
    assert fake_browser.events() == ["visibilitychange"]
    watcher.destroy()
    assert fake_browser.events() == []
    assert events_module.ffi.destroyed  # the imperative subscription went with it


# ── Levels ─────────────────────────────────────────────────────────────────────

class HeldKey(Component):
    __tag__ = "x-events-held"
    escape_held = key_held("Escape")

    def template(self):
        """<div class="held"></div>"""


def test_a_held_key_is_a_field_the_browser_maintains(fake_browser):
    """The level half of the mechanism: a real field, written as the answer changes."""
    widget = HeldKey.mount(Element("div", attrs={}, children=[]))
    assert widget.escape_held is False  # the neutral, before anything happens

    fake_browser.dispatch("keydown", key="Escape")
    assert widget.escape_held is True

    fake_browser.dispatch("keyup", key="Escape")
    assert widget.escape_held is False

    widget.destroy()


def test_losing_the_window_releases_a_held_key(fake_browser):
    """A ``keyup`` is lost if the window blurs first, so ``blur`` writes the neutral too."""
    widget = HeldKey.mount(Element("div", attrs={}, children=[]))
    fake_browser.dispatch("keydown", key="Escape")
    assert widget.escape_held is True

    events_module.window.dispatch("blur")

    assert widget.escape_held is False
    widget.destroy()


def test_a_level_is_an_observation_and_an_edge_is_an_action(fake_browser):
    """A field that says "the key is down" is not competing for the keystroke, so the
    typing guard does not apply to it — while the handler beside it stays guarded."""
    editor = FakeElement(tag="div", content_editable=True)

    class Typing(Component):
        __tag__ = "x-events-typing"
        escape_held = key_held("Escape")
        dismissals = 0

        @on_key("Escape")
        def dismiss(self, event):
            self.dismissals += 1

        def template(self):
            """<div class="typing"></div>"""

    widget = Typing.mount(Element("div", attrs={}, children=[]))

    fake_browser.dispatch("keydown", key="Escape", target=editor)

    assert widget.escape_held is True
    assert widget.dismissals == 0
    widget.destroy()


def test_pointer_and_visibility_are_levels_too(fake_browser):
    class Aware(Component):
        __tag__ = "x-events-aware"
        pointer_down = pointer_held()
        hidden = document_hidden()

        def template(self):
            """<div class="aware"></div>"""

    widget = Aware.mount(Element("div", attrs={}, children=[]))
    assert (widget.pointer_down, widget.hidden) == (False, False)

    fake_browser.dispatch("pointerdown")
    assert widget.pointer_down is True
    fake_browser.dispatch("pointercancel")
    assert widget.pointer_down is False

    events_module.document.visibilityState = "hidden"
    fake_browser.dispatch("visibilitychange")
    assert widget.hidden is True

    widget.destroy()


def test_a_store_can_declare_a_level(fake_browser):
    class UiStore(Store):
        shift_held = key_held("Shift")

    store = UiStore("test_events_levels")
    store.on_client_ready()

    fake_browser.dispatch("keydown", key="Shift")
    assert store.shift_held is True

    store.on_client_teardown()
    assert store.shift_held is True  # the value outlives the registration


# ── Declarations ───────────────────────────────────────────────────────────────

def test_declarations_are_collected_from_the_whole_class():
    class Base(Owner):
        @on_key("Escape")
        def dismiss(self, event):
            pass

        @on_global("visibilitychange")
        def visibility(self, event):
            pass

    class Derived(Base):
        @on_key("K", mod=True)
        def save(self, event):
            pass

    declared = declared_declarations(Derived)

    assert set(declared) == {"dismiss", "save", "visibility"}
    assert declared["dismiss"][0].event == "keydown"
    assert declared["save"][0].matcher.mod is True
    assert declared["visibility"][0].event == "visibilitychange"


def test_one_handler_may_declare_several_observations(fake_browser):
    """Cmd-K and Cmd-P are the same action, so they are the same method."""
    class Shortcuts(Component):
        __tag__ = "x-events-shortcuts"
        hits = 0

        @on_key("K", mod=True)
        @on_key("P", mod=True)
        def toggle(self, event):
            self.hits += 1

        def template(self):
            """<div class="shortcuts"></div>"""

    assert [d.matcher.key for d in declared_declarations(Shortcuts)["toggle"]] == ["P", "K"]

    shortcuts = Shortcuts.mount(Element("div", attrs={}, children=[]))
    assert fake_browser.events() == ["keydown"]  # one registration for both

    fake_browser.dispatch("keydown", key="k", ctrl=True)
    fake_browser.dispatch("keydown", key="p", meta=True)
    assert shortcuts.hits == 2


def test_a_higher_ranked_owner_takes_the_key(fake_browser):
    """Stacked overlays: the modal ranks above the drawer, so only the modal closes."""
    class Drawer(Owner):
        def __init__(self):
            super().__init__()
            self.closed = False

        @on_key("Escape", when="open")
        def dismiss(self, event):
            event.claim()
            self.closed = True

    class Modal(Drawer):
        @on_key("Escape", when="open", priority=10)
        def dismiss(self, event):
            event.claim()
            self.closed = True

    drawer, modal = Drawer(), Modal()
    drawer.open = modal.open = True
    subscribe("document", "keydown", drawer.dismiss, when="open", owner=drawer)
    subscribe("document", "keydown", modal.dismiss, when="open", owner=modal, priority=10)

    fake_browser.dispatch("keydown", key="Escape")

    assert (modal.closed, drawer.closed) == (True, False)


def test_an_override_without_a_declaration_withdraws_the_inherited_one():
    class Base(Owner):
        @on_key("Escape")
        def dismiss(self, event):
            pass

    class Derived(Base):
        def dismiss(self, event):  # no decorator: the page calls this one
            pass

    assert declared_declarations(Derived) == {}


def test_a_component_whose_declaration_is_overridden_attaches_only_once(fake_browser):
    class Base(Component):
        __tag__ = "x-events-base"
        hits = 0

        @on_key("Escape")
        def dismiss(self, event):
            self.hits += 1

        def template(self):
            """<div class="base"></div>"""

    class Derived(Base):
        __tag__ = "x-events-derived"

    component = Derived.mount(Element("div", attrs={}, children=[]))
    fake_browser.dispatch("keydown", key="Escape")

    assert component.hits == 1
    assert fake_browser.events() == ["keydown"]


def test_a_declaration_that_names_an_unresolvable_gate_fails_at_attach(fake_browser):
    class Broken(Component):
        __tag__ = "x-events-broken"

        @on_key("Escape", when="openned")  # typo
        def dismiss(self, event):
            pass

        def template(self):
            """<div class="broken"></div>"""

    with pytest.raises(ValueError):
        Broken.mount(Element("div", attrs={}, children=[]))


def test_phase_and_combo_are_validated_at_declaration_time():
    with pytest.raises(ValueError):
        on_key("Escape", phase="sideways")
    with pytest.raises(ValueError):
        on_key("")
