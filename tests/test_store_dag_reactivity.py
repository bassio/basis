"""
Tests for the unified DAG-based reactivity engine on Store.

Validates that:
1. @computed properties work on Store subclasses
2. Store-to-Component DAG subscription propagation works
3. Dynamic attribute creation on Store auto-creates StateNodes
4. refrain() on Store batches multiple attribute changes
5. Wildcard subscriptions fire on any public attribute change
"""
from contextvars import Context

import pytest
from typing import ClassVar
from unittest.mock import MagicMock, call

from basis.shared import store as store_module
from basis.shared.app_state import AppStateStore
from basis.shared.reactive import ReactiveObject, DependencyGraph, computed, Refrain, batch, state
from basis.shared.store import ModelStore, Store, WebSocketStore, install_initial_state
from basis.shared.context import ContextVarProxyDict


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _clear_store_registry():
    """Clear the store registries between tests.

    Both the per-context instance registry AND the persistent blueprint registry
    must be reset — otherwise a store name reused across tests with a different
    local class (e.g. ``CartStore("cart")`` in two test methods) trips the
    conflict guard.
    """
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()
    install_initial_state({})


# ──────────────────────────────────────────────
# Test: ReactiveObject basics
# ──────────────────────────────────────────────

class TestReactiveObjectBasics:
    def test_reactive_object_has_dag(self):
        obj = ReactiveObject()
        assert hasattr(obj, '_dag')
        assert isinstance(obj._dag, DependencyGraph)

    def test_reactive_object_setattr_creates_state_node(self):
        obj = ReactiveObject()
        obj.x = 10
        assert 'x' in obj._dag.nodes
        assert obj.x == 10

    def test_reactive_object_private_attrs_bypass_dag(self):
        obj = ReactiveObject()
        obj._internal = "secret"
        assert '_internal' not in obj._dag.nodes
        assert obj._internal == "secret"

    def test_declared_defaults_are_materialized_per_instance(self):
        class Basket(ReactiveObject):
            count = 0
            items: list[int] = state(default_factory=list)

        first = Basket()
        second = Basket()

        assert first.__dict__["count"] == 0
        assert first.items == []
        assert first.items is not second.items
        assert first._state_fields == {"count": "declared", "items": "declared"}

    def test_inherited_state_uses_mro_overrides_and_excludes_classvars(self):
        class Parent(ReactiveObject):
            inherited = "parent"
            setting: ClassVar[str] = "configuration"

        class Child(Parent):
            inherited = "child"
            setting = {"child": True}
            required: int

        child = Child()

        assert child.inherited == "child"
        assert "setting" not in child.__dict__
        assert child._required_state_fields == frozenset({"required"})

    def test_mutable_class_default_requires_a_factory(self):
        with pytest.raises(TypeError, match="Invalid.items.*state\\(default_factory"):
            class Invalid(ReactiveObject):
                items = []

    def test_state_rejects_invalid_default_arguments(self):
        with pytest.raises(TypeError, match="exactly one"):
            state()
        with pytest.raises(TypeError, match="immutable"):
            state(default=[])
        with pytest.raises(TypeError, match="callable"):
            state(default_factory=[])

    def test_reactive_object_change_detection_identity(self):
        """Same identity → no trigger."""
        obj = ReactiveObject()
        obj.x = 42
        # Track effect
        calls = []
        obj._dag.add_effect("test_effect", lambda: calls.append("fired"), ["x"])
        obj.x = 42  # same value, same identity
        assert calls == []

    def test_reactive_object_change_detection_different_value(self):
        obj = ReactiveObject()
        obj.x = 42
        calls = []
        obj._dag.add_effect("test_effect", lambda: calls.append("fired"), ["x"])
        obj.x = 99
        assert calls == ["fired"]

    def test_reactive_object_collection_always_triggers(self):
        """Mutable collections always trigger even with == equality."""
        obj = ReactiveObject()
        items = [1, 2, 3]
        obj.items = items
        calls = []
        obj._dag.add_effect("test_effect", lambda: calls.append("fired"), ["items"])
        obj.items = items  # same identity — should NOT trigger
        assert calls == []
        obj.items = [1, 2, 3]  # different identity, same content — SHOULD trigger (collections)
        assert calls == ["fired"]

    def test_refrain_batches_updates(self):
        obj = ReactiveObject()
        obj.a = 1
        obj.b = 2
        calls = []
        obj._dag.add_effect("effect_a", lambda: calls.append("a"), ["a"])
        obj._dag.add_effect("effect_b", lambda: calls.append("b"), ["b"])
        calls.clear()  # clear any initial triggers

        with obj.refrain() as r:
            r.a = 10
            r.b = 20
        
        # Both should fire exactly once (batched)
        assert obj.a == 10
        assert obj.b == 20
        assert "a" in calls
        assert "b" in calls

    def test_refrain_skips_writes_that_do_not_move_the_value(self):
        """A batch must not dirty the graph for a redundant write."""
        obj = ReactiveObject()
        obj.a = 1
        calls = []
        obj._dag.add_effect("effect_a", lambda: calls.append("a"), ["a"])
        calls.clear()

        with obj.refrain() as r:
            r.a = 1  # identical
        assert calls == []

        with obj.refrain() as r:
            r.a = 2  # real change
        assert calls == ["a"]

    def test_refrain_still_triggers_new_attributes(self):
        obj = ReactiveObject()
        calls = []
        obj._dag.add_effect("effect_a", lambda: calls.append("a"), ["a"])
        calls.clear()

        with obj.refrain() as r:
            r.a = 1  # not previously set
        assert calls == ["a"]

    def test_refrain_treats_a_new_container_identity_as_a_change(self):
        """Container semantics match ``__setattr__``: identity, not content."""
        obj = ReactiveObject()
        obj.items = [1]
        calls = []
        obj._dag.add_effect("effect_items", lambda: calls.append("i"), ["items"])
        calls.clear()

        with obj.refrain() as r:
            r.items = [1]
        assert calls == ["i"]

    def test_refrain_force_react_bypasses_the_change_guard(self):
        obj = ReactiveObject()
        obj.a = 1
        calls = []
        obj._dag.add_effect("effect_a", lambda: calls.append("a"), ["a"])
        calls.clear()

        with obj.refrain() as r:
            r.a = 1
            r.force_react("a")
        assert calls == ["a"]

    def test_react_triggers_dag(self):
        obj = ReactiveObject()
        obj.x = 1
        calls = []
        obj._dag.add_effect("test_effect", lambda: calls.append("fired"), ["x"])
        calls.clear()
        obj.react(["x"])
        assert calls == ["fired"]


# ──────────────────────────────────────────────
# Test: Store inherits ReactiveObject
# ──────────────────────────────────────────────

class TestStoreReactivity:
    def setup_method(self):
        _clear_store_registry()

    def test_store_is_reactive_object(self):
        store = Store("test_store")
        assert isinstance(store, ReactiveObject)
        assert hasattr(store, '_dag')

    def test_store_has_loading_and_error_state_nodes(self):
        store = Store("test_store")
        assert 'loading' in store._dag.nodes
        assert 'error' in store._dag.nodes

    def test_store_setattr_creates_state_nodes(self):
        store = Store("test_store")
        store.items = [1, 2, 3]
        assert 'items' in store._dag.nodes
        assert store.items == [1, 2, 3]

    def test_serialize_includes_defaults_and_omits_local_state(self):
        class Preferences(Store):
            mode = "system"
            editing: bool = state(default=False, serialize=False)

        store = Preferences("preferences")

        assert store.serialize()["mode"] == "system"
        assert "editing" not in store.serialize()

    def test_snapshot_wins_after_the_complete_constructor(self, monkeypatch):
        install_initial_state({"preferences": {"mode": "dark"}})

        class Preferences(Store):
            mode = "system"

            def __init__(self, name):
                super().__init__(name)
                self.mode = "light"

        class SpecializedPreferences(Preferences):
            def __init__(self, name):
                super().__init__(name)
                self.mode = "contrast"

        preferences = SpecializedPreferences("preferences")

        assert preferences.mode == "dark"
        assert preferences.serialize()["mode"] == "dark"
        assert Store.resolve("preferences") is preferences

    def test_pending_subscriber_observes_only_final_state(self, monkeypatch):
        install_initial_state({"preferences": {"mode": "dark"}})
        seen = []

        class Subscriber(ReactiveObject):
            def react(self, names):
                seen.append(Store._registry["preferences"].mode)

        subscriber = Subscriber()
        subscriber._dag.add_effect(
            "capture",
            lambda: subscriber.react(["$preferences.mode"]),
            ["$preferences.mode"],
        )
        Store._pending_subscriptions["preferences"] = [(subscriber, "mode")]

        class Preferences(Store):
            mode = "system"

            def __init__(self, name):
                super().__init__(name)
                self.mode = "light"

        Preferences("preferences")

        assert seen == ["dark"]

    def test_failed_constructor_cannot_displace_a_working_store(self):
        class Fragile(Store):
            @classmethod
            def _capture_config(cls, fail=False):
                return {}

            def __init__(self, name, *, fail=False):
                super().__init__(name)
                if fail:
                    raise RuntimeError("construction failed")

        working = Fragile("fragile")

        with pytest.raises(RuntimeError, match="construction failed"):
            Fragile("fragile", fail=True)

        assert Store._registry["fragile"] is working

    def test_resolve_returns_the_active_instance(self):
        store = Store("stable")

        assert Store.resolve("stable") is store

    def test_from_dict_publishes_explicit_initial_state(self):
        seen = []

        class Subscriber(ReactiveObject):
            def react(self, names):
                seen.append(Store._registry["payload"].value)

        subscriber = Subscriber()
        subscriber._dag.add_effect(
            "capture",
            lambda: subscriber.react(["$payload.value"]),
            ["$payload.value"],
        )
        Store._pending_subscriptions["payload"] = [(subscriber, "value")]

        store = Store.from_dict("payload", {"value": 7})

        assert store.value == 7
        assert seen == [7]

    def test_invalid_initial_state_cannot_replace_a_working_store(self):
        working = Store("payload")

        with pytest.raises(ValueError, match="serialize"):
            Store.from_dict("payload", {"serialize": "invalid"})

        assert Store.resolve("payload") is working

    def test_explicit_empty_state_does_not_merge_the_browser_snapshot(self, monkeypatch):
        install_initial_state({"preferences": {"mode": "dark"}})

        class Preferences(Store):
            mode = "system"

            def __init__(self, name):
                super().__init__(name)
                self.mode = "light"

        preferences = Preferences.from_dict("preferences", {})

        assert preferences.mode == "light"
        assert preferences._initial_load is None

        rebuilt = Store.reinstantiate("preferences")
        assert rebuilt.mode == "light"

    def test_boot_snapshot_is_consumed_after_successful_publication(self):
        install_initial_state({"preferences": {"mode": "dark"}})

        class Preferences(Store):
            mode = "system"

        hydrated = Preferences("preferences")
        rebuilt = Store.reinstantiate("preferences")

        assert hydrated.mode == "dark"
        assert rebuilt.mode == "system"

    def test_failed_construction_releases_the_boot_snapshot(self):
        install_initial_state({"required": {}})

        class RequiredStore(Store):
            value: int

        with pytest.raises(TypeError, match="RequiredStore.*value"):
            RequiredStore("required")

        install_initial_state({"required": {"value": 7}})
        assert RequiredStore("required").value == 7

    def test_failed_snapshot_preparation_leaves_entry_claimable(self):
        install_initial_state({"payload": {"serialize": "invalid"}})

        with pytest.raises(ValueError, match="serialize"):
            Store("payload")

        with pytest.raises(ValueError, match="serialize"):
            Store("payload")

    def test_empty_boot_snapshot_is_present_and_consumed(self):
        install_initial_state({"preferences": {}})

        class Preferences(Store):
            mode = "system"

            def __init__(self, name):
                super().__init__(name)
                self.mode = "light"

        hydrated = Preferences("preferences")
        rebuilt = Store.reinstantiate("preferences")

        assert hydrated._initial_load.snapshot_applied is True
        assert hydrated.mode == "light"
        assert rebuilt._initial_load is None

    def test_late_store_claims_retained_boot_entry(self):
        install_initial_state({"late": {"ready": True}})
        Store("unrelated")

        late = Store("late")

        assert late.ready is True
        assert late._initial_load.snapshot_applied is True

    def test_required_state_fails_before_publication(self):
        class RequiredStore(Store):
            value: int

        with pytest.raises(TypeError, match="RequiredStore.*value"):
            RequiredStore("required")

        assert "required" not in Store._registry
        assert "required" not in Store._store_blueprints

    def test_active_registries_are_context_local(self):
        first_context = Context()
        second_context = Context()

        first = first_context.run(Store, "scoped")
        second = second_context.run(Store.resolve, "scoped")

        assert first is not second
        assert first_context.run(Store.resolve, "scoped") is first
        assert second_context.run(Store.resolve, "scoped") is second

    def test_websocket_activation_waits_for_client_ready(self, monkeypatch):
        sockets = []

        class FakeSocket:
            def __init__(self, url):
                self.url = url
                self.onmessage = None
                self.closed = False

            def close(self):
                self.closed = True

        class FakeWebSocket:
            @staticmethod
            def new(url):
                socket = FakeSocket(url)
                sockets.append(socket)
                return socket

        monkeypatch.setattr(store_module, "WebSocket", FakeWebSocket)
        store = WebSocketStore("updates", "wss://example.test/updates")

        assert sockets == []
        store.on_client_ready()
        assert [socket.url for socket in sockets] == ["wss://example.test/updates"]
        store.on_client_teardown()
        assert sockets[0].closed is True

    def test_store_subclasses_cannot_override_allocation(self):
        with pytest.raises(TypeError, match="CustomAllocation.*cannot define __new__"):
            class CustomAllocation(Store):
                def __new__(cls, name):
                    return super().__new__(cls)

    def test_store_private_attrs_bypass_dag(self):
        store = Store("test_store")
        store.__dict__['_custom'] = "private"
        assert '_custom' not in store._dag.nodes

    def test_store_setattr_triggers_dag(self):
        store = Store("test_store")
        store.count = 0
        calls = []
        store._dag.add_effect("test_effect", lambda: calls.append("fired"), ["count"])
        calls.clear()
        store.count = 5
        assert calls == ["fired"]

    def test_store_refrain_batches(self):
        store = Store("test_store")
        store.x = 1
        store.y = 2
        calls = []
        store._dag.add_effect("ex", lambda: calls.append("x"), ["x"])
        store._dag.add_effect("ey", lambda: calls.append("y"), ["y"])
        calls.clear()

        with store.refrain() as r:
            r.x = 10
            r.y = 20

        assert store.x == 10
        assert store.y == 20
        assert "x" in calls
        assert "y" in calls

    def test_apply_state_batches_fields_and_preserves_omitted_values(self):
        store = Store("test_store")
        store.x = 1
        store.y = 2
        store.untouched = 3
        seen = []
        store._dag.add_effect(
            "pair", lambda: seen.append((store.x, store.y)), ["x", "y"]
        )

        result = store.apply_state({"x": 10, "y": 20})

        assert result is None
        assert seen == [(10, 20)]
        assert store.untouched == 3

    def test_apply_state_respects_outer_batch_and_empty_patch(self):
        store = Store("test_store")
        store.x = 1
        store.y = 2
        seen = []
        store._dag.add_effect(
            "pair", lambda: seen.append((store.x, store.y)), ["x", "y"]
        )

        assert store.apply_state({}) is None
        assert seen == []
        with batch():
            store.apply_state({"x": 10})
            store.apply_state({"y": 20})
            assert seen == []

        assert seen == [(10, 20)]

    def test_apply_state_rejects_invalid_keys_before_mutating(self):
        store = Store("test_store")
        store.value = 1

        for invalid_key in ("_private", "not-valid", "serialize"):
            with pytest.raises(ValueError, match=invalid_key):
                store.apply_state({"value": 2, invalid_key: 3})
            assert store.value == 1

    def test_apply_state_rejects_local_only_fields(self):
        class Preferences(Store):
            editing: bool = state(default=False, serialize=False)

        store = Preferences("preferences")

        with pytest.raises(ValueError, match="editing"):
            store.apply_state({"editing": True})
        assert store.editing is False

    def test_apply_state_accepts_unknown_public_data_fields(self):
        store = Store("test_store")

        store.apply_state({"dynamic_value": 7})

        assert store.dynamic_value == 7
        assert store.serialize()["dynamic_value"] == 7

    def test_missing_store_reads_raise_attribute_error_before_loading(self):
        store = Store("test_store")

        with pytest.raises(AttributeError, match="missing"):
            _ = store.missing


@pytest.mark.parametrize(
    "store_factory",
    [
        lambda name: Store(name),
        lambda name: AppStateStore(name),
        lambda name: ModelStore(name, type("SnapshotModel", (), {})),
    ],
    ids=["store", "app-state-store", "model-store"],
)
def test_store_families_share_state_application(store_factory):
    _clear_store_registry()
    store = store_factory("state_family")
    store.value = 1

    result = store.apply_state({"value": 2})

    assert result is None
    assert store.value == 2
    _clear_store_registry()


# ──────────────────────────────────────────────
# Test: @computed on Store
# ──────────────────────────────────────────────

class TestStoreComputed:
    def setup_method(self):
        _clear_store_registry()

    def test_computed_property_on_store(self):
        class CartStore(Store):
            items: list = state(default_factory=list)

            @computed
            def item_count(self):
                return len(self.items)

        store = CartStore("cart")
        assert store.item_count == 0

        store.items = [{"name": "Apple"}, {"name": "Banana"}]
        assert store.item_count == 2

    def test_computed_property_updates_on_dependency_change(self):
        class PriceStore(Store):
            price = 100
            tax_rate = 0.1

            @computed
            def total(self):
                return self.price * (1 + self.tax_rate)

        store = PriceStore("prices")
        assert store.total == pytest.approx(110.0)

        store.price = 200
        assert store.total == pytest.approx(220.0)

        store.tax_rate = 0.2
        assert store.total == pytest.approx(240.0)

    def test_computed_with_explicit_dependencies(self):
        class MyStore(Store):
            first_name = "John"
            last_name = "Doe"

            @computed(dependencies=["first_name", "last_name"])
            def full_name(self):
                return f"{self.first_name} {self.last_name}"

        store = MyStore("user")
        assert store.full_name == "John Doe"

        store.first_name = "Jane"
        assert store.full_name == "Jane Doe"


# ──────────────────────────────────────────────
# Test: Store Subscription via DAG
# ──────────────────────────────────────────────

class TestStoreSubscriptions:
    def setup_method(self):
        _clear_store_registry()

    def test_add_subscription_creates_effect_node(self):
        store = Store("test_store")
        mock_component = MagicMock()
        mock_component.react = MagicMock()

        store.add_subscription(mock_component, "items")
        
        # Effect node should exist
        effect_name = f"sub_{id(mock_component)}_items"
        assert effect_name in store._dag.nodes

    def test_attribute_subscription_fires_on_change(self):
        store = Store("test_store")
        mock_component = MagicMock()
        mock_component.react = MagicMock()

        store.add_subscription(mock_component, "items")
        store.items = ["apple", "banana"]

        mock_component.react.assert_called_with(["$test_store.items"])

    def test_attribute_subscription_does_not_fire_for_unrelated_attr(self):
        store = Store("test_store")
        mock_component = MagicMock()
        mock_component.react = MagicMock()

        store.add_subscription(mock_component, "items")
        mock_component.react.reset_mock()
        
        store.other_attr = "something"
        
        # Should NOT have been called with items
        for c in mock_component.react.call_args_list:
            assert "$test_store.items" not in c[0][0]

    def test_wildcard_subscription_fires_on_any_change(self):
        store = Store("test_store")
        mock_component = MagicMock()
        mock_component.react = MagicMock()

        store.add_subscription(mock_component, "")  # whole-store

        store.items = [1, 2, 3]
        mock_component.react.assert_called_with(["$test_store"])

    def test_wildcard_subscription_fires_on_new_attributes(self):
        store = Store("test_store")
        mock_component = MagicMock()
        mock_component.react = MagicMock()

        store.add_subscription(mock_component, "")  # whole-store
        mock_component.react.reset_mock()

        # Setting a completely new attribute should still trigger the wildcard
        store.brand_new_attr = "hello"
        mock_component.react.assert_called_with(["$test_store"])

    def test_remove_subscription_removes_effect(self):
        store = Store("test_store")
        mock_component = MagicMock()
        mock_component.react = MagicMock()

        store.add_subscription(mock_component, "items")
        effect_name = f"sub_{id(mock_component)}_items"
        assert effect_name in store._dag.nodes

        store.remove_subscription(mock_component, "items")
        assert effect_name not in store._dag.nodes

    def test_subscription_to_computed_property(self):
        """Component subscribing to a computed store property should react when it changes."""
        class CartStore(Store):
            items: list = state(default_factory=list)

            @computed
            def count(self):
                return len(self.items)

        store = CartStore("cart")
        mock_component = MagicMock()
        mock_component.react = MagicMock()

        store.add_subscription(mock_component, "count")
        mock_component.react.reset_mock()

        store.items = ["a", "b", "c"]
        # The computed 'count' depends on 'items'. When items changes,
        # 'count' is marked stale, and the subscription effect should fire.
        mock_component.react.assert_called_with(["$cart.count"])


# ──────────────────────────────────────────────
# Test: Multiple subscriptions
# ──────────────────────────────────────────────

class TestMultipleSubscriptions:
    def setup_method(self):
        _clear_store_registry()

    def test_multiple_components_subscribe(self):
        store = Store("shared")
        comp1 = MagicMock()
        comp1.react = MagicMock()
        comp2 = MagicMock()
        comp2.react = MagicMock()

        store.add_subscription(comp1, "value")
        store.add_subscription(comp2, "value")

        store.value = 42

        comp1.react.assert_called_with(["$shared.value"])
        comp2.react.assert_called_with(["$shared.value"])

    def test_mixed_attr_and_wildcard_subscriptions(self):
        store = Store("mixed")
        attr_comp = MagicMock()
        attr_comp.react = MagicMock()
        wildcard_comp = MagicMock()
        wildcard_comp.react = MagicMock()

        store.add_subscription(attr_comp, "x")
        store.add_subscription(wildcard_comp, "")

        store.x = 10

        attr_comp.react.assert_called_with(["$mixed.x"])
        wildcard_comp.react.assert_called_with(["$mixed"])
