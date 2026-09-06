"""
Component lifecycle contract — P0 regression harness + P1 unmount tests for
``COMPONENT-LIFECYCLE-PLAN.md``.

P0 pinned TODAY's component lifecycle semantics on the server model (the server
side of an SSR render); those pins still guard the mount-side contract so the
refactor cannot change it silently. P1 added a real ``Component.destroy()`` +
``on_unmounted()``; the two P0 pins that documented the *gaps* (shallow
ChildBinding destroy, custom-element loop-child store-subscription leak) were
deliberately FLIPPED to assert the fixed behavior.

Every test documents exactly what it pins and which phase will *deliberately*
change it.

Coverage boundary (why some plan items are documented here, not asserted):
- ``on_mounted`` running in the *client CSR* and *client detached-SSR-shadow*
  environments, and ``on_hydrated`` firing only at the end of the client-only
  ``initialize_ssr`` pass, are CLIENT/Pyodide behaviors — not reachable from
  this server-model harness. The shared ordering this suite DOES pin (bindings
  live + element attached when ``on_mounted`` runs) lives in
  ``BaseComponent.initialize`` and therefore governs the server render AND both
  client mount environments identically. ``on_hydrated``'s client-only firing is
  exercised by the existing hydration / js_component / region suites.
"""

import pytest

from basis.shared.base_component import BaseComponent
from basis.shared.bindings import ChildBinding
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.store import Store

import basis.shared.reactive as _reactive


@pytest.fixture(autouse=True)
def _clean_state():
    """Isolate registries/dictionaries that the lifecycle touches."""
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    _reactive._wake_list.clear()
    yield
    _reactive._wake_list.clear()


def _mount(cls, **attrs):
    """Mount into a fresh container element (server model)."""
    return cls.mount(Element("div", attrs={}, children=[]), **attrs)


def _loop(owner):
    return next(b for b in owner.__bindings__ if b.__class__.__name__ == "LoopBinding")


# ---------------------------------------------------------------------------
# Mount-side contract
# ---------------------------------------------------------------------------

def test_on_mounted_runs_once_with_live_bindings_on_server_mount():
    """Server mount (the server half of an SSR render) runs ``on_mounted``
    EXACTLY ONCE, at the END of ``BaseComponent.initialize``: the root element
    is already set and every binding is live (``activate()`` ran, DAG effects
    registered). This shared order lives in shared ``initialize()``, so it also
    governs client CSR and the client SSR-shadow staging mount. P1 must keep
    ``on_mounted`` on this same tail-of-initialize call site."""
    history = []

    class Life(Component):
        __tag__ = "x-life-mount"

        def on_mounted(self):
            history.append(
                (len(self.__bindings__),
                 self.__element__ is not None,
                 self.__element__.tagName.lower())
            )

        def template(self):
            """<div class="life">hi</div>"""

    _mount(Life)
    assert history == [(1, True, "div")]


def test_on_hydrated_is_not_part_of_server_mount():
    """Hydration is a client-only concept: mounting (server SSR render / client
    CSR) NEVER calls ``on_hydrated`` — that hook fires only from the client's
    ``initialize_ssr`` re-pointing pass. Pins that ``on_mounted`` and
    ``on_hydrated`` are two DISJOINT entry points (the "which hook where" table
    in the plan §3.2), so P1 cannot accidentally start invoking hydration hooks
    on the server or during plain mounts."""
    history = []

    class Life(Component):
        __tag__ = "x-life-hydrated"

        def on_mounted(self):
            history.append("mounted")

        def on_hydrated(self):
            history.append("hydrated")

        def template(self):
            """<div class="life">x</div>"""

    _mount(Life)
    assert history == ["mounted"]


# ---------------------------------------------------------------------------
# Hide vs unmount
# ---------------------------------------------------------------------------

def test_if_hide_keeps_child_mounted_and_reveal_reattaches():
    """IfBinding HIDE detaches the child's wrapper from the DOM but does NOT
    unmount it: the child instance, its scope effects and bindings stay live so
    re-show works WITHOUT a remount. This pins hide ≠ unmount (plan §3.3) —
    P1's recursive ``destroy()`` must never be triggered by an if-hide."""
    class Inner(Component):
        __tag__ = "x-life-hide-inner"
        label = ""

        def template(self):
            """<span class="inner">{label}</span>"""

    class Reveal(Component):
        __tag__ = "x-life-hide-reveal"
        show = False

        def template(self):
            """
            <div class="reveal">
                <x-life-hide-inner if="{show}" label="in"></x-life-hide-inner>
            </div>
            """

    reveal = _mount(Reveal)
    cb = next(b for b in reveal.__bindings__ if b.__class__.__name__ == "ChildBinding")
    child = cb.childinstance
    assert child is not None

    # Hidden: the <x-life-hide-inner> WRAPPER is detached, but the child is
    # mounted and its scope effects are alive.
    assert cb.node.parentNode is None
    effect_names = [n for _, n in child._scope._effects]
    assert effect_names

    # Reveal re-attaches the SAME wrapper — no remount, no teardown.
    reveal.show = True
    assert cb.node.parentNode is not None
    assert [n for _, n in child._scope._effects] == effect_names


def test_remove_binding_on_child_recursively_destroys_child():
    """P1 FLIP: removing a ChildBinding now RECURSIVELY unmounts the child — its
    scope effects / DAG nodes are torn down and the instance is marked
    destroyed (no more "reclaimed with the subtree" optimism). This was the
    shallow-destroy pin (child effects survived)."""
    class Inner(Component):
        __tag__ = "x-life-shallow-inner"
        text = ""

        def template(self):
            """<span class="inner">{text}</span>"""

    class Outer(Component):
        __tag__ = "x-life-shallow-outer"

        def template(self):
            """
            <div class="outer">
                <x-life-shallow-inner text="a"></x-life-shallow-inner>
            </div>
            """

    outer = _mount(Outer)
    cb = next(b for b in outer.__bindings__ if isinstance(b, ChildBinding))
    child = cb.childinstance
    effect_names = [n for _, n in child._scope._effects]
    assert effect_names

    outer.remove_binding(cb)
    assert cb.childinstance is None
    assert child._destroyed is True
    assert child._scope._effects == []
    assert all(name not in child._dag.nodes for name in effect_names)


# ---------------------------------------------------------------------------
# Teardown substrate (what P1's Component.destroy() will build on)
# ---------------------------------------------------------------------------

def test_scope_destroy_removes_cross_object_store_subscription_edge():
    """The teardown substrate region/HMR rely on today: destroying a
    component's ROOT scope removes its ``$store`` subscription edges from the
    STORE's DAG (the ``sub_*`` effect is added on the store graph and recorded
    on the component scope via ``record_effect``). P1's ``Component.destroy()``
    will invoke exactly this — pin it so the substrate can't regress."""
    store = Store("counter")

    class Bound(Component):
        __tag__ = "x-life-storebound"

        def template(self):
            """<div>{$counter.count}</div>"""

    inst = _mount(Bound)
    edges = [n for n in store._dag.nodes if n.startswith("sub_")]
    assert len(edges) == 1

    inst._scope.destroy()
    assert [n for n in store._dag.nodes if n.startswith("sub_")] == []


def test_custom_element_loop_child_store_subscription_removed_on_item_removal():
    """P1 FLIP: removing a custom-element loop child now REALLY unmounts it —
    the child component's own root scope is destroyed, so the ``$store``
    subscription it registered (a ``sub_*`` effect on the STORE's DAG) is
    removed and the child is no longer kept alive. This was the leak pin (the
    edge survived item removal)."""
    store = Store("counter")

    class Entry(Component):
        __tag__ = "x-life-loop-entry"
        label = ""

        def template(self):
            """<div class="entry">{$counter.count}:{label}</div>"""

    class Owner(Component):
        __tag__ = "x-life-loop-owner"
        items = []

        def template(self):
            """
            <div class="owner">
                <x-life-loop-entry for="it" in="{items}" key="k" label="{it['label']}"></x-life-loop-entry>
            </div>
            """

    owner = _mount(Owner)
    owner.items = [{"k": 1, "label": "a"}]
    lb = _loop(owner)
    entry = next(iter(lb.instances.values()))
    child = entry.instance
    assert child is not None

    edges = [n for n in store._dag.nodes if n.startswith("sub_")]
    assert len(edges) == 1

    owner.items = []  # removes the item through the normal reconciliation path
    assert len(lb.instances) == 0
    assert child._destroyed is True
    assert [n for n in store._dag.nodes if n.startswith("sub_")] == []


# ---------------------------------------------------------------------------
# The one component-unmount that exists today: <ui-region> item removal
# ---------------------------------------------------------------------------

class Pill(Component):
    """Module-level contribution class so ``resolve_component`` can import it
    by ``module.ClassName`` (region contributions must be importable)."""

    text = ""

    def template(self):
        """<span class="pill">{text}</span>"""


def test_region_removal_tears_down_contribution_scope_and_node():
    """``<ui-region>`` item removal routes through the full P1/P2
    ``Component.destroy()`` — the contribution's scope effects are cleared, its
    DOM node is removed, the instance is marked destroyed and (via destroy's
    cascade) its nested children are unmounted. P0 pinned the pre-P2 contract
    (ad hoc scope-destroy + node.remove, no on_unmounted); Phase 2 adopted full
    destroy() here, so the observable contract is now the destroy contract."""
    from basis.plugins.regions.region import Region
    from basis.plugins.regions.registry import cls_path_of
    from basis.plugins.regions.store import RegionStore

    region_store = RegionStore("regions")
    region_store.__dict__["items"] = {}  # avoid double-hydration guards
    region_store.add_local("sb", cls_path_of(Pill), {"text": "x"})

    region = _mount(Region, name="sb")
    assert list(region._region_mounted.keys()) == [cls_path_of(Pill)]
    instance = next(iter(region._region_mounted.values()))
    assert isinstance(instance, Pill)
    effect_names = [n for _, n in instance._scope._effects]
    assert effect_names
    node = instance.__element__  # capture BEFORE destroy nulls the element

    # Remove the contribution from the store and re-sync the region (the live
    # path `<ui-region>` uses when a plugin/contribution is disabled).
    region_store.remove_local("sb", cls_path_of(Pill))
    region._sync()

    assert region._region_mounted == {}
    assert instance._destroyed is True
    assert [n for _, n in instance._scope._effects] == []  # scope destroyed
    assert node.parentNode is None                          # node removed


# ---------------------------------------------------------------------------
# Phase 1 — Component.destroy() / on_unmounted()
# ---------------------------------------------------------------------------

def test_destroy_is_idempotent_removes_element_and_calls_on_unmounted_once():
    """P1: ``destroy()`` removes the root element from the DOM and calls
    ``on_unmounted()`` exactly once, AFTER the framework state is clean (element
    already removed, ``_destroyed`` set). A second ``destroy()`` is a no-op."""
    calls = []

    class Card(Component):
        __tag__ = "x-life-destroy-card"

        def on_unmounted(self):
            calls.append(
                ("unmounted",
                 self.__dict__.get("_element") is None,
                 self.__dict__.get("_destroyed", False))
            )

        def template(self):
            """<div class="card">hi</div>"""

    inst = _mount(Card)
    root_element = inst.__element__
    assert root_element.parentNode is not None
    assert inst._destroyed is False

    inst.destroy()
    assert inst._destroyed is True
    assert calls == [("unmounted", True, True)]
    assert root_element.parentNode is None

    inst.destroy()  # idempotent
    assert len(calls) == 1


def test_destroy_removes_store_subscription_edges():
    """P1: destroying a component removes the ``sub_*`` edges it registered on
    the store's DAG (its root scope is destroyed) — the component no longer
    keeps the store's effect graph alive."""
    store = Store("counter")

    class Bound(Component):
        __tag__ = "x-life-destroy-storebound"

        def template(self):
            """<div>{$counter.count}</div>"""

    inst = _mount(Bound)
    assert [n for n in store._dag.nodes if n.startswith("sub_")]

    inst.destroy()
    assert inst._destroyed is True
    assert [n for n in store._dag.nodes if n.startswith("sub_")] == []


def test_destroy_cascades_through_nested_child_subtree():
    """P1: destroying a root component recurses through its ChildBinding tree —
    every descendant is destroyed (marked + scope torn down) and descendant
    store-subscription edges are removed from the store's DAG."""
    store = Store("counter")

    class Leaf(Component):
        __tag__ = "x-life-destroy-leaf"

        def template(self):
            """<span class="leaf">{$counter.count}</span>"""

    class Mid(Component):
        __tag__ = "x-life-destroy-mid"

        def template(self):
            """<div class="mid"><x-life-destroy-leaf></x-life-destroy-leaf></div>"""

    class Root(Component):
        __tag__ = "x-life-destroy-root"

        def template(self):
            """<div class="root"><x-life-destroy-mid></x-life-destroy-mid></div>"""

    root = _mount(Root)
    mid = next(b for b in root.__bindings__ if isinstance(b, ChildBinding)).childinstance
    leaf = next(b for b in mid.__bindings__ if isinstance(b, ChildBinding)).childinstance
    assert len([n for n in store._dag.nodes if n.startswith("sub_")]) == 1

    root.destroy()
    assert root._destroyed is True
    assert mid._destroyed is True
    assert leaf._destroyed is True
    assert leaf._scope._effects == []
    assert [n for n in store._dag.nodes if n.startswith("sub_")] == []


def test_destroy_recurses_into_if_hidden_child():
    """P1 (plan R1): destroying a component also unmounts descendants that are
    currently HIDDEN by an if-binding (they are part of its subtree) — without
    an explicit destroy, an if-hide alone never unmounts anything."""
    class Hidden(Component):
        __tag__ = "x-life-destroy-hidden"
        label = ""

        def template(self):
            """<span class="hidden">{label}</span>"""

    class Host(Component):
        __tag__ = "x-life-destroy-host"
        show = False

        def template(self):
            """<div class="host"><x-life-destroy-hidden if="{show}" label="h"></x-life-destroy-hidden></div>"""

    host = _mount(Host)
    cb = next(b for b in host.__bindings__ if isinstance(b, ChildBinding))
    child = cb.childinstance
    assert child is not None
    assert cb.node.parentNode is None  # hidden at mount

    host.destroy()
    assert child._destroyed is True  # R1: hidden descendants are unmounted too
    assert cb.node.parentNode is None


def test_destroy_deregisters_instance_identity():
    """P1: destroying a component deregisters its ``#id``/``__component_id__``
    identity from the instance registry (plan R4 — a later mount with the same
    identity re-registers cleanly)."""
    class Panel(Component):
        __tag__ = "x-life-destroy-panel"

        def template(self):
            """<div id="panel-root">hi</div>"""

    inst = _mount(Panel)
    assert BaseComponent._instance_registry["panel-root"] is inst

    inst.destroy()
    assert "panel-root" not in BaseComponent._instance_registry

    # R4: a fresh mount with the same #id re-registers cleanly.
    inst2 = _mount(Panel)
    assert BaseComponent._instance_registry["panel-root"] is inst2
    inst2.destroy()
    assert "panel-root" not in BaseComponent._instance_registry


def test_destroy_drains_pending_subscriptions():
    """P1: a component waiting on a store/component that never arrived (a
    pending ``$``/``#`` subscription) has its pending entry removed on destroy,
    so the queue cannot pin a dead instance."""
    class Waiting(Component):
        __tag__ = "x-life-destroy-waiting"

        def template(self):
            """<div>{$ghost_store.count}</div>"""

    inst = _mount(Waiting)
    pending = Store._pending_subscriptions
    assert any(e[0] is inst for e in pending.get("ghost_store", []))

    inst.destroy()
    # No pending entry may still reference the destroyed instance.
    assert all(e[0] is not inst for e in pending.get("ghost_store", []))


# ---------------------------------------------------------------------------
# Phase 2 — destroy() is reachable: region adopts full destroy, JsComponent
# boot-race guard, whole-loop cascade (tests only)
# ---------------------------------------------------------------------------

class LoggedLeaf(Component):
    """Nested template child of a region contribution; records ``on_unmounted``
    on a class-level log so tests can assert full-destroy recursion through a
    removed contribution."""

    __tag__ = "x-life-p2-logged-leaf"
    text = ""
    log = []

    def on_unmounted(self):
        self.log.append("leaf")

    def template(self):
        """<span class="logged-leaf">{text}</span>"""


class LoggedPill(Component):
    """Module-level region contribution that owns a nested ``LoggedLeaf`` child.
    Records its own ``on_unmounted`` so tests can assert the contribution is
    really unmounted via ``Component.destroy()`` (not the old ad hoc
    scope-destroy + node.remove)."""

    text = ""
    log = []

    def on_unmounted(self):
        self.log.append("pill")

    def template(self):
        """
        <div class="logged-pill">
            <x-life-p2-logged-leaf text="{text}"></x-life-p2-logged-leaf>
        </div>
        """


def test_region_item_removal_routes_through_destroy_and_cascades():
    """P2: ``<ui-region>`` ``_sync`` removal now routes through the P1
    ``Component.destroy()`` (the ad hoc ``_scope.destroy()`` + ``node.remove()``
    is gone), so a removed contribution is REALLY unmounted: scope effects
    cleared, DOM node removed, ``_destroyed`` set, ``on_unmounted`` fired AND
    the recursion reaches its nested child."""
    from basis.plugins.regions.region import Region
    from basis.plugins.regions.registry import cls_path_of
    from basis.plugins.regions.store import RegionStore

    LoggedPill.log = []
    LoggedLeaf.log = []

    region_store = RegionStore("regions")
    region_store.__dict__["items"] = {}  # avoid double-hydration guards
    region_store.add_local("sb", cls_path_of(LoggedPill), {"text": "x"})

    region = _mount(Region, name="sb")
    instance = region._region_mounted[cls_path_of(LoggedPill)]
    child = next(b for b in instance.__bindings__ if isinstance(b, ChildBinding)).childinstance
    assert child is not None
    assert [n for n, _ in instance._scope._effects]  # contribution scope live
    node = instance.__element__  # capture BEFORE destroy nulls the element

    region_store.remove_local("sb", cls_path_of(LoggedPill))
    region._sync()

    assert region._region_mounted == {}
    assert instance._destroyed is True
    assert child._destroyed is True                    # recursion into the subtree
    assert instance._scope._effects == []              # scope torn down
    assert node.parentNode is None                     # node removed
    assert LoggedPill.log == ["pill"]                  # on_unmounted fired once
    assert LoggedLeaf.log == ["leaf"]                  # nested on_unmounted fired


def test_region_destroy_cleans_leftover_contributions():
    """P2: destroying the ``<ui-region>`` itself (``Component.destroy()``)
    unmounts contributions still held in ``_region_mounted`` via the region's
    ``on_unmounted`` hook — contributions are imperative mounts with NO binding
    edge, so ``destroy()``'s binding recursion cannot reach them without it."""
    from basis.plugins.regions.region import Region
    from basis.plugins.regions.registry import cls_path_of
    from basis.plugins.regions.store import RegionStore

    region_store = RegionStore("regions")
    region_store.__dict__["items"] = {}  # avoid double-hydration guards
    region_store.add_local("sb", cls_path_of(Pill), {"text": "x"})

    region = _mount(Region, name="sb")
    instance = next(iter(region._region_mounted.values()))
    assert instance is not None
    node = instance.__element__  # capture BEFORE destroy nulls the element

    region.destroy()
    assert region._destroyed is True
    assert region._region_mounted == {}
    assert instance._destroyed is True
    assert node.parentNode is None


def test_owner_destroy_cascades_into_custom_element_loop_children():
    """P2 (tests only): destroying an owner whose template contains a whole
    LoopBinding over custom-element children destroys every live loop child —
    ``LoopBinding.destroy`` drops each item's ChildBinding, which (P1) destroys
    the child, removing its store-subscription edges."""
    store = Store("counter")

    class Entry(Component):
        __tag__ = "x-life-p2-loop-entry"
        label = ""

        def template(self):
            """<span class="entry2">{$counter.count}:{label}</span>"""

    class Owner(Component):
        __tag__ = "x-life-p2-loop-owner"
        items = []

        def template(self):
            """
            <div class="owner2">
                <x-life-p2-loop-entry for="it" in="{items}" key="k" label="{it['label']}"></x-life-p2-loop-entry>
            </div>
            """

    owner = _mount(Owner)
    owner.items = [{"k": 1, "label": "a"}, {"k": 2, "label": "b"}]
    lb = _loop(owner)
    children = [e.instance for e in lb.instances.values()]
    assert all(c is not None for c in children)
    assert [n for n in store._dag.nodes if n.startswith("sub_")]  # child edges live

    owner.destroy()
    assert all(c._destroyed for c in children)
    assert [n for n in store._dag.nodes if n.startswith("sub_")] == []


def test_js_component_destroy_blocks_pending_boot():
    """P2: ``@js_component`` destroyed mid-boot can never land on a dead node.
    The in-flight state is ``_js_booted = True`` (set by ``_boot()`` before the
    ES-module ``await``); ``destroy()`` sets ``_destroyed`` and clears
    ``_js_booted`` (via ``_teardown_js``), so ``_boot_async``'s post-await guard
    (``_destroyed or not _js_booted``) is always true — ``boot_js`` is never
    called on a destroyed instance. (Server-side pin of the guard condition; the
    client-only await/``boot_js`` path is covered by the js_component suite.)"""
    from basis.shared.js_component import JsComponent

    class Widget(JsComponent):
        __tag__ = "x-life-p2-js-widget"

        def template(self):
            """<div class="widget">js</div>"""

    inst = _mount(Widget)
    assert inst._js_booted is False

    inst.__dict__["_js_booted"] = True  # simulate in-flight _boot()
    inst.destroy()                      # destroy while the module load is pending
    assert inst._destroyed is True
    assert inst._js_booted is False
    assert inst._destroyed or not inst._js_booted  # the post-await guard holds
