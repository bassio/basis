"""
P5 — invariants & DX (REACTIVITY-OVERHAUL.md P5).

- The AST dependency-extraction path is GONE: @computed deps come from
  execution tracking only (an explicit ``dependencies=[...]`` list is still
  honored as declared deps), and the dead ``dag.py`` compat shim was deleted.
- Dependency edges of a @computed are PRIMED at registration (a tracking
  dry-run that computes no value and swallows errors), so a computed that is
  subscribed to but never rendered still propagates.
- Dev warning: a @computed that computes with NO reactive dependencies warns
  once (it will never recompute); @derived nodes are exempt (item-data-only
  deps are legitimate).
"""
import importlib

import pytest

from basis.shared.base_component import BaseComponent
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.reactive import _wake_list, computed, derived
from basis.shared.store import Store


@pytest.fixture(autouse=True)
def _clean_state():
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    _wake_list.clear()
    yield
    _wake_list.clear()


def _mount(cls, **attrs):
    return cls.mount(Element("div", attrs={}, children=[]), **attrs)


def _text_of(node):
    if node is None:
        return None
    return getattr(node, "textContent", None) or "".join(
        _text_of(c) for c in getattr(node, "children", [])
    )


# ─────────────────────────────────────────────
# Execution tracking is the dep source (no AST)
# ─────────────────────────────────────────────

def test_computed_auto_deps_tracked_through_helper():
    """Deps are discovered by execution tracking, NOT AST: a computed reading
    through a helper method still re-runs when the underlying state changes.
    (Under the old AST extractor this was DEAD — it only saw `_helper`.)"""
    class C(Component):
        __tag__ = "x-dx-helper"
        name = "Ada"

        def _helper(self):
            return self.name.upper()

        @computed
        def shout(self):
            return self._helper()

        def template(self):
            """<div><span>{shout}</span></div>"""

    comp = _mount(C)
    assert "ADA" in _text_of(comp.__element__)
    comp.name = "Grace"
    assert "GRACE" in _text_of(comp.__element__)


def test_manual_dependencies_still_honored():
    """An explicit ``dependencies=[...]`` list is honored even when the body
    does NOT read the named field — the declared dep is re-attached on every
    update and still triggers recompute (the `$store.x`-style relay hatch)."""
    class M(Store):
        a = 1

        def __init__(self, name):
            self.__dict__["_calls"] = 0
            super().__init__(name)

        @computed(dependencies=["a"])
        def d(self):
            self.__dict__["_calls"] += 1
            return 100

    store = M("manual")
    store.__dict__["_calls"] = 0  # ignore the init-time priming dry-run
    assert store.d == 100
    assert store.__dict__["_calls"] == 1
    store.a = 5  # declared dep recomputes even though the body never reads `a`
    assert store.d == 100
    assert store.__dict__["_calls"] == 2


# ─────────────────────────────────────────────
# Subscription-only computeds still propagate (primed edges)
# ─────────────────────────────────────────────

def test_subscription_to_never_read_computed_propagates():
    """A component subscribing to a Store @computed that is never rendered still
    reacts when the computed's deps change — dependency edges are primed at
    registration, not only on first read."""
    from unittest.mock import MagicMock

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
    mock_component.react.assert_called_with(["$cart.count"])


# ─────────────────────────────────────────────
# Empty-dep dev warning (@computed only)
# ─────────────────────────────────────────────

def test_empty_dep_computed_warns_once(capsys):
    """A @computed that computes with NO reactive dependencies warns once — it
    will never recompute."""
    class C(Component):
        __tag__ = "x-dx-empty"

        @computed
        def c(self):
            return 42

        def template(self):
            """<div><span>hi</span></div>"""

    comp = _mount(C)
    capsys.readouterr()  # drain mount-time output (priming prints nothing)
    assert comp.c == 42
    out = capsys.readouterr().out
    assert "Basis Reactivity Warning" in out
    assert "no reactive dependencies" in out
    # Memoized second read — no second warning.
    assert comp.c == 42
    assert "no reactive dependencies" not in capsys.readouterr().out


def test_derived_with_item_only_deps_does_not_warn(capsys):
    """A @derived whose only reads are item data (no tracked deps) does NOT warn
    — it is invalidated by item reuse, not by tracked deps."""
    class Owner(Component):
        items = []

        @derived
        def label(self, it):
            return it["name"]

        def template(self):
            """
            <div>
                <div for="it" in="{items}">
                    <span>{label}</span>
                </div>
            </div>
            """

    mounted = _mount(Owner)
    capsys.readouterr()
    mounted.items = [{"name": "x"}]
    assert "x" in _text_of(mounted.__element__)
    assert "no reactive dependencies" not in capsys.readouterr().out


# ─────────────────────────────────────────────
# AST path deleted
# ─────────────────────────────────────────────

def test_ast_extraction_removed():
    """DependencyVisitor / extract_func_dependencies are gone, and the dead
    dag.py compat shim was deleted."""
    with pytest.raises(ImportError):
        importlib.import_module("basis.shared.dag")

    from basis.shared import reactive as r
    assert not hasattr(r, "DependencyVisitor")
    assert not hasattr(r, "extract_func_dependencies")
