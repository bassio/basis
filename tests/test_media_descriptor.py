"""Tests for ``media()`` / ``MediaQuery`` / ``MediaMixin``.

The client path runs against fake ``window``/``ffi`` objects, because these tests
execute server-side where the real ones are absent.
"""
import pytest

from basis.shared import js as js_module
from basis.shared import media as media_module
from basis.shared import store as store_module
from basis.shared.media import MediaQuery, install_media_resync, media
from basis.shared.reactive import computed
from basis.shared.store import Store
from js_fakes import FakeFFI


def _clear_registries():
    """Drop store instances/blueprints and every query's runtime state.

    A name or query reused across tests with different config trips the conflict
    guards, so both registries are reset around every test.
    """
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()
    # The multiton entries themselves persist (class declarations outlive a test),
    # so only the browser-side state is dropped — each test gets a fresh fake window.
    for query in list(MediaQuery._instance_registry.values()):
        query.mql = None
        query.listener = None
        query.targets = []


class FakeMQL:
    """Stand-in for ``MediaQueryList``."""

    def __init__(self, query):
        self.query = query
        self.matches = False
        self.listeners = []
        self.removed = []

    def addEventListener(self, name, fn):
        self.listeners.append((name, fn))

    def removeEventListener(self, name, fn):
        self.removed.append((name, fn))
        self.listeners = [pair for pair in self.listeners if pair != (name, fn)]


class FakeWindow:
    def __init__(self):
        self.by_query = {}
        self.listeners = []

    def matchMedia(self, query):
        return self.by_query.setdefault(query, FakeMQL(query))

    def set_matches(self, query, value):
        """Answer *query* before anything asks for it."""
        self.matchMedia(query).matches = value

    def addEventListener(self, name, fn):
        self.listeners.append((name, fn))


class FakeEvent:
    def __init__(self, matches):
        self.matches = matches


class LayoutStore(Store):
    """A plain store — the mechanism needs no specialised base class."""

    narrow = media("(width <= 600px)")
    wide = media("(width >= 1000px)", default=True)


class DerivedLayoutStore(Store):
    narrow = media("(width <= 600px)")

    @computed
    def cols(self):
        return 1 if self.narrow else 3


class BaseStore(Store):
    narrow = media("(width <= 700px)")


class ChildStore(BaseStore):
    wide = media("(width >= 1100px)")


class OverridingStore(BaseStore):
    narrow = media("(width <= 480px)")


@pytest.fixture(autouse=True)
def isolate_registries(monkeypatch):
    monkeypatch.setattr(store_module, "_client_ready", False)
    monkeypatch.setattr(media_module, "_resync_installed", False)
    media_module._resync_listeners.clear()
    _clear_registries()
    yield
    media_module._resync_listeners.clear()
    _clear_registries()


@pytest.fixture
def browser(monkeypatch):
    """Make the client path runnable server-side."""
    win, fake_ffi = FakeWindow(), FakeFFI()
    monkeypatch.setattr(media_module, "window", win)
    monkeypatch.setattr(js_module, "ffi", fake_ffi)
    return win, fake_ffi


class TestDeclaration:
    def test_declares_query_and_neutral(self):
        declaration = media("(min-resolution: 2dppx)", default=True)
        assert declaration.query == "(min-resolution: 2dppx)"
        assert declaration.default is True

    def test_query_is_stripped(self):
        assert media("  (orientation: portrait)  ").query == "(orientation: portrait)"

    @pytest.mark.parametrize("bad", ["", "   ", None, 5])
    def test_invalid_query_rejected(self, bad):
        with pytest.raises(ValueError):
            media(bad)

    def test_same_query_string_returns_the_same_instance(self):
        assert media("(pointer: coarse)") is media("(pointer: coarse)")

    def test_distinct_query_strings_are_distinct_instances(self):
        assert media("(pointer: fine)") is not media("(pointer: coarse)")

    def test_conflicting_neutrals_are_rejected(self):
        media("(hover: none)")
        with pytest.raises(ValueError):
            media("(hover: none)", default=True)

    def test_registered_on_the_owning_class(self):
        assert set(LayoutStore.declared_media()) == {"narrow", "wide"}

    def test_merges_across_inheritance(self):
        assert set(ChildStore.declared_media()) == {"narrow", "wide"}

    def test_subclass_override_wins(self):
        assert OverridingStore.declared_media()["narrow"].query == "(width <= 480px)"

    def test_subclass_does_not_mutate_the_parent_map(self):
        assert set(BaseStore.declared_media()) == {"narrow"}

    def test_store_without_declarations(self):
        class Plain(Store):
            pass

        assert Plain.declared_media() == {}

    def test_one_instance_serves_every_declaration_site(self):
        assert LayoutStore.declared_media()["narrow"] is DerivedLayoutStore.declared_media()["narrow"]


class TestMaterialisation:
    def test_declared_fields_become_real_fields(self):
        store = LayoutStore("mat_fields")
        assert store.__dict__["narrow"] is False
        assert store.__dict__["wide"] is True

    def test_inherited_declarations_materialize(self):
        store = ChildStore("mat_child")
        assert store.narrow is False

    def test_class_attribute_stays_the_descriptor(self):
        assert isinstance(LayoutStore.__dict__["narrow"], MediaQuery)

    def test_reads_return_the_field_not_the_descriptor(self):
        store = LayoutStore("mat_reads")
        store.narrow = True
        assert store.narrow is True

    def test_read_before_materialisation_is_the_neutral(self):
        assert LayoutStore.__dict__["wide"].__get__(object()) is True

    def test_fields_get_dag_nodes(self):
        store = LayoutStore("mat_nodes")
        assert "narrow" in store._dag.nodes

    def test_serialize_includes_declared_fields(self):
        state = LayoutStore("mat_serialize").serialize()
        assert state["narrow"] is False
        assert state["wide"] is True

    def test_missing_field_is_restored(self):
        """The guard is absence, not the hydration flag."""
        store = LayoutStore("mat_restore")
        del store.__dict__["narrow"]
        store._materialize_media()
        assert store.__dict__["narrow"] is False

    def test_existing_values_are_left_alone(self):
        store = LayoutStore("mat_keep")
        store.narrow = True
        store._materialize_media()
        assert store.narrow is True

    def test_store_without_declarations_is_untouched(self):
        class Plain(Store):
            pass

        plain = Plain("mat_plain")
        assert "narrow" not in plain.__dict__

    def test_computed_reacts_to_a_declared_field(self):
        store = DerivedLayoutStore("mat_computed")
        assert store.cols == 3
        store.narrow = True
        assert store.cols == 1


class TestClientLifecycle:
    def test_attach_without_window_is_a_noop(self):
        store = LayoutStore("cli_nowindow")
        store._attach_media()
        assert "_media_handles" not in store.__dict__

    def test_attach_ignores_stores_without_declarations(self, browser):
        class Plain(Store):
            pass

        store = Plain("cli_plain")
        store._attach_media()
        assert "_media_handles" not in store.__dict__

    def test_attach_registers_one_change_listener_per_query(self, browser):
        win, _ = browser
        store = LayoutStore("cli_attach")
        store._attach_media()
        assert set(store.__dict__["_media_handles"]) == {"narrow", "wide"}
        assert [name for name, _fn in win.by_query["(width <= 600px)"].listeners] == ["change"]

    def test_attach_is_idempotent(self, browser):
        win, _ = browser
        store = LayoutStore("cli_idempotent")
        store._attach_media()
        store._attach_media()
        assert len(win.by_query["(width <= 600px)"].listeners) == 1

    def test_attach_reads_the_current_answer(self, browser):
        win, _ = browser
        win.set_matches("(width <= 600px)", True)
        store = LayoutStore("cli_initial")
        store._attach_media()
        assert store.narrow is True

    def test_change_listener_writes_the_field(self, browser):
        win, _ = browser
        store = LayoutStore("cli_change")
        store._attach_media()
        _name, listener = win.by_query["(width <= 600px)"].listeners[0]
        listener(FakeEvent(True))
        assert store.narrow is True
        listener(FakeEvent(0))
        assert store.narrow is False

    def test_change_listener_writes_every_target(self, browser):
        win, _ = browser
        first, second = LayoutStore("cli_t1"), DerivedLayoutStore("cli_t2")
        first._attach_media()
        second._attach_media()
        _name, listener = win.by_query["(width <= 600px)"].listeners[0]
        listener(FakeEvent(True))
        assert first.narrow is True
        assert second.narrow is True

    def test_resync_that_moves_nothing_fires_nothing(self, browser, monkeypatch):
        win, _ = browser
        store = LayoutStore("cli_resync_quiet")
        store._attach_media()
        triggered = []
        monkeypatch.setattr(
            store._dag, "trigger_batch", lambda names: triggered.append(sorted(names))
        )
        store._resync_media()
        assert triggered == []
        win.by_query["(width <= 600px)"].matches = True
        store._resync_media()
        assert triggered == [["narrow"]]
        assert store.narrow is True

    def test_detach_removes_listeners_and_proxies(self, browser):
        win, fake_ffi = browser
        store = LayoutStore("cli_detach")
        store._attach_media()
        mql = win.by_query["(width <= 600px)"]
        store._detach_media()
        assert [name for name, _fn in mql.removed] == ["change"]
        assert "_media_handles" not in store.__dict__
        assert len(fake_ffi.destroyed) == 2

    def test_detach_is_idempotent(self, browser):
        store = LayoutStore("cli_detach_twice")
        store._attach_media()
        store._detach_media()
        store._detach_media()

    def test_client_hooks_delegate(self, browser):
        store = LayoutStore("cli_hooks")
        store.on_client_ready()
        assert "_media_handles" in store.__dict__
        store.on_client_teardown()
        assert "_media_handles" not in store.__dict__

    def test_store_built_after_ready_attaches_itself(self, browser, monkeypatch):
        monkeypatch.setattr(store_module, "_client_ready", True)
        store = LayoutStore("cli_late")
        assert "_media_handles" in store.__dict__

    def test_displaced_store_is_detached(self, browser):
        win, _ = browser
        first = LayoutStore("cli_displaced")
        first.on_client_ready()
        mql = win.by_query["(width <= 600px)"]
        second = LayoutStore("cli_displaced")
        assert [name for name, _fn in mql.removed] == ["change"]
        assert mql.listeners == []
        second.on_client_ready()
        assert len(mql.listeners) == 1


class TestQuerySharing:
    def test_one_listener_serves_every_declarer(self, browser):
        win, fake_ffi = browser
        first, second = LayoutStore("share_a"), LayoutStore("share_b")
        first._attach_media()
        second._attach_media()
        assert len(win.by_query["(width <= 600px)"].listeners) == 1
        assert len(fake_ffi.created) == 2  # one per distinct query string

    def test_browser_object_survives_until_the_last_owner_leaves(self, browser):
        win, fake_ffi = browser
        first, second = LayoutStore("release_a"), LayoutStore("release_b")
        first._attach_media()
        second._attach_media()
        mql = win.by_query["(width <= 600px)"]

        first._detach_media()
        assert len(mql.listeners) == 1
        assert fake_ffi.destroyed == []

        second._detach_media()
        assert mql.listeners == []
        assert len(fake_ffi.destroyed) == 2

    def test_registry_keeps_the_declaration_after_release(self, browser):
        win, _ = browser
        store = LayoutStore("release_keep")
        store._attach_media()
        store._detach_media()
        assert MediaQuery._instance_registry.get("(width <= 600px)") is LayoutStore.declared_media()["narrow"]


class TestResyncInstaller:
    def test_registers_once(self, browser):
        win, _ = browser
        install_media_resync(Store._registry)
        install_media_resync(Store._registry)
        assert [name for name, _fn in win.listeners] == ["resize", "orientationchange"]

    def test_drives_a_resizing_store(self, browser):
        win, _ = browser
        store = LayoutStore("cli_resize_all")
        store._attach_media()
        install_media_resync(Store._registry)
        _name, listener = win.listeners[0]
        win.by_query["(width <= 600px)"].matches = True
        listener(None)
        assert store.narrow is True

    def test_without_window_is_a_noop(self):
        install_media_resync(Store._registry)
