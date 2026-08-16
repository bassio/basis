"""
Tests for the unified DAG-based reactivity engine on Store.

Validates that:
1. @computed properties work on Store subclasses
2. Store-to-Component DAG subscription propagation works
3. Dynamic attribute creation on Store auto-creates StateNodes
4. refrain() on Store batches multiple attribute changes
5. Wildcard subscriptions fire on any public attribute change
"""
import pytest
from unittest.mock import MagicMock, call

from basis.shared.reactive import ReactiveObject, DependencyGraph, computed, Refrain
from basis.shared.store import Store
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


# ──────────────────────────────────────────────
# Test: @computed on Store
# ──────────────────────────────────────────────

class TestStoreComputed:
    def setup_method(self):
        _clear_store_registry()

    def test_computed_property_on_store(self):
        class CartStore(Store):
            items = []

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
            items = []

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
