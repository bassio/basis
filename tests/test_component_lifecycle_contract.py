"""
Component lifecycle contract: the mount-side semantics this framework promises,
plus the unmount path (``Component.destroy()`` + ``on_unmounted()``).

The pins here guard the mount-side contract so a refactor cannot change it
silently, and assert that teardown really unmounts (ChildBinding destroys its
child subtree; a custom-element loop child's store subscriptions are released).

Every test documents exactly what it pins.

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
from typing import ClassVar

from basis.shared.base_component import (
    BaseComponent,
    _effective_store_inclusions,
    include_store,
)
from basis.shared.bindings import ChildBinding
from basis.shared.component import Component
from basis.shared.element import Element, ElementString
from basis.shared.reactive import computed, state
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
    ``on_hydrated`` are two DISJOINT entry points — a mount must not invoke
    hydration hooks on the server or during plain mounts."""
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


def test_component_state_factories_are_instance_owned():
    class ListView(Component):
        __tag__ = "x-life-state-factory"
        items: list[str] = state(default_factory=list)

        def template(self):
            """<div>{items}</div>"""

    first = _mount(ListView)
    second = _mount(ListView)

    assert first.items == []
    assert first.items is not second.items

    first.destroy()
    second.destroy()


def test_computed_metadata_is_not_rescanned_per_mount(monkeypatch):
    class Summary(Component):
        __tag__ = "x-life-computed-definition"
        value = 2

        @computed(dependencies=["value"])
        def doubled(self):
            return self.value * 2

        def template(self):
            """<div>{doubled}</div>"""

    def rescan(*args, **kwargs):
        raise AssertionError("computed metadata was rescanned during mount")

    monkeypatch.setattr(_reactive.inspect, "getmembers", rescan)

    first = _mount(Summary)
    second = _mount(Summary)

    assert first.__element__.childNodes[0].textContent == "4"
    assert second.__element__.childNodes[0].textContent == "4"

    first.destroy()
    second.destroy()


def test_hot_swap_reconciles_state_before_rebuilt_bindings_evaluate():
    evaluations = []
    factory_calls = []

    class OldView(Component):
        __tag__ = "x-life-hot-old"
        title = "old default"
        removed = "remove me"

        def template(self):
            """<div>{title}</div>"""

    view = _mount(OldView)
    view.title = "live title"
    view.hidden = "dynamic value"

    class NewView(Component):
        __tag__ = "x-life-hot-new"
        title = "new default"
        added: list[str] = state(
            default_factory=lambda: factory_calls.append("called") or []
        )

        @computed
        def summary(self):
            evaluations.append((self.title, self.hidden, self.added))
            return f"{self.title}:{self.hidden}:{len(self.added)}"

        def template(self):
            """<div>{summary}</div>"""

    view.hot_swap(NewView)

    assert type(view) is NewView
    assert view.title == "live title"
    assert view.hidden == "dynamic value"
    assert view.added == []
    assert "removed" not in view.__dict__
    assert evaluations
    assert all(
        evaluation == ("live title", "dynamic value", [])
        for evaluation in evaluations
    )
    assert factory_calls == ["called"]
    assert view.__element__.childNodes[0].textContent == "live title:dynamic value:0"

    view.destroy()


def test_hot_swap_preserves_creation_props_and_drops_new_behavior_collisions():
    callback = lambda: "called"

    class OldView(Component):
        __tag__ = "x-life-hot-props-old"
        source = "initial"

        def template(self):
            """<div>{source}</div>"""

    view = _mount(OldView, title="{source}", callback=callback)
    view.source = "preserved"
    view.collision = "dynamic"

    class NewView(Component):
        __tag__ = "x-life-hot-props-new"
        source = "new"

        def collision(self):
            return "behavior"

        def template(self):
            """<section>{source}</section>"""

    view.hot_swap(NewView)

    assert view.callback is callback
    assert "collision" not in view.__dict__
    assert view.collision() == "behavior"
    assert view.title == "preserved"
    assert view.__element__.childNodes[0].textContent == "preserved"

    view.destroy()


def test_hot_swap_reconnects_store_subscriptions_without_identity_growth():
    store = Store("hot_counter")
    store.value = "before"

    class OldView(Component):
        __tag__ = "x-life-hot-store-old"
        __component_id__ = "hot-store-view"

        def template(self):
            """<div>{$hot_counter.value}</div>"""

    class NewView(Component):
        __tag__ = "x-life-hot-store-new"
        __component_id__ = "hot-store-view"

        def template(self):
            """<section>{$hot_counter.value}</section>"""

    view = _mount(OldView)
    view.hot_swap(NewView)
    store.value = "after"

    assert view.__element__.childNodes[0].textContent == "after"
    assert view._registered_identities == ["hot-store-view"]
    assert store._subscriptions == [(view, "value")]
    assert len([name for name in store._dag.nodes if name.startswith("sub_")]) == 1

    view.destroy()


def test_hot_swap_mounts_nested_children_from_the_new_definition():
    class OldView(Component):
        __tag__ = "x-life-hot-nested-old"

        class OldChild(Component):
            __tag__ = "x-life-hot-nested-old-child"

            def template(self):
                """<span>old</span>"""

        def template(self):
            """<div></div>"""

    class NewView(Component):
        __tag__ = "x-life-hot-nested-new"

        class NewChild(Component):
            __tag__ = "x-life-hot-nested-new-child"

            def template(self):
                """<strong>new</strong>"""

        def template(self):
            """<section></section>"""

    view = _mount(OldView)
    old_child = _child_of(view, OldView.OldChild)
    view.hot_swap(NewView)

    assert old_child._destroyed is True
    assert isinstance(_child_of(view, NewView.NewChild), NewView.NewChild)

    view.destroy()


def test_hot_swap_moves_existing_slot_content_into_the_new_template():
    light = Element("span", attrs={"class": "light"}, children=[ElementString("kept")])
    container = Element("div", attrs={}, children=[light])
    light.parent = container

    class OldView(Component):
        __tag__ = "x-life-hot-slot-old"

        def template(self):
            """<div><slot></slot></div>"""

    class NewView(Component):
        __tag__ = "x-life-hot-slot-new"

        def template(self):
            """<section><header>new</header><slot></slot></section>"""

    view = OldView.mount(container)
    view.hot_swap(NewView)

    assert light.parentNode is view.__element__
    assert light in view.__element__.childNodes

    view.destroy()


def test_hot_swap_restarts_js_backed_resources_on_the_new_element():
    calls = []

    class OldWidget(Component):
        __tag__ = "x-life-hot-js-old"
        __js_component__ = True

        def _teardown_js(self):
            calls.append(("teardown", self.__element__.tagName.lower()))

        def template(self):
            """<div>old</div>"""

    class NewWidget(Component):
        __tag__ = "x-life-hot-js-new"
        __js_component__ = True

        def on_mounted(self):
            calls.append(("mounted", self.__element__.tagName.lower()))

        def template(self):
            """<section>new</section>"""

    widget = _mount(OldWidget)
    widget.hot_swap(NewWidget)

    assert calls == [("teardown", "div"), ("mounted", "section")]

    widget.destroy()


def test_mount_preserves_authored_class_and_registry_identity():
    class Counter(Component):
        __tag__ = "x-life-stable-definition"
        count = 0

        def template(self):
            """<button>{count}</button>"""

    registered = BaseComponent._registry[Counter.__tag__]

    first = _mount(Counter, count=1)
    second = _mount(Counter, count=2)

    assert type(first) is Counter
    assert type(second) is Counter
    assert BaseComponent._registry[Counter.__tag__] is registered is Counter
    assert first.__element__ is not second.__element__
    assert first.__bindings__[0] is not second.__bindings__[0]

    first.destroy()
    second.destroy()


def test_typed_and_callback_props_are_borrowed_instance_values():
    class PropView(Component):
        __tag__ = "x-life-typed-props"
        items = None
        on_select = None

        def template(self):
            """<div>{items}</div>"""

    items = [{"id": 1}]
    callback = lambda item: item

    view = _mount(PropView, items=items, on_select=callback)

    assert type(view) is PropView
    assert view.items is items
    assert view.on_select is callback
    assert "items" not in PropView.__dict__ or PropView.__dict__["items"] is None
    assert PropView.__dict__["on_select"] is None

    view.destroy()


@pytest.mark.parametrize("name", ["_scope", "destroy", "configuration"])
def test_creation_props_reject_private_behavior_and_configuration(name):
    class Protected(Component):
        __tag__ = "x-life-protected-props"
        configuration: ClassVar[str] = "fixed"

        def template(self):
            """<div></div>"""

    with pytest.raises(ValueError, match=name):
        _mount(Protected, **{name: "invalid"})


def test_store_inclusions_are_owned_and_resolved_through_the_mro():
    @include_store("shared", url="/left")
    @include_store("left")
    class Left(Component):
        def template(self):
            """<div></div>"""

    @include_store("right")
    class Right(Component):
        def template(self):
            """<div></div>"""

    @include_store("shared", url="/child")
    @include_store("child")
    class Child(Left, Right):
        pass

    assert tuple(item.name for item in Left.__dict__["__basis_stores__"]) == (
        "left",
        "shared",
    )
    assert tuple(item.name for item in Right.__dict__["__basis_stores__"]) == ("right",)
    assert tuple(item.name for item in Child.__dict__["__basis_stores__"]) == (
        "child",
        "shared",
    )

    effective = _effective_store_inclusions(Child)
    assert tuple(item.name for item in effective) == ("right", "left", "shared", "child")
    assert next(item for item in effective if item.name == "shared").url == "/child"


def test_definition_compiles_once_per_revision(monkeypatch):
    calls = []
    initialize_blueprint = Component._initialize_blueprint.__func__
    analyze_template = Component._analyze_template.__func__

    def counted_initialize(cls):
        calls.append(("blueprint", cls))
        return initialize_blueprint(cls)

    def counted_analyze(cls):
        calls.append(("analyze", cls))
        return analyze_template(cls)

    monkeypatch.setattr(Component, "_initialize_blueprint", classmethod(counted_initialize))
    monkeypatch.setattr(Component, "_analyze_template", classmethod(counted_analyze))

    class Prepared(Component):
        __tag__ = "x-life-prepared-definition"
        value = 0

        def template(self):
            """<div>{value}</div>"""

    assert calls == []

    Prepared.ensure_definition()
    Prepared.ensure_definition()
    first = _mount(Prepared, value=1)
    second = _mount(Prepared, value=2)

    assert calls == [("blueprint", Prepared), ("analyze", Prepared)]
    assert isinstance(Prepared.__binding_blueprints__, tuple)

    Prepared.invalidate_definition()
    Prepared.ensure_definition()
    assert calls == [
        ("blueprint", Prepared),
        ("analyze", Prepared),
        ("blueprint", Prepared),
        ("analyze", Prepared),
    ]

    first.destroy()
    second.destroy()


# ---------------------------------------------------------------------------
# Hide vs unmount
# ---------------------------------------------------------------------------

def test_if_hide_keeps_child_mounted_and_reveal_reattaches():
    """IfBinding HIDE detaches the child's wrapper from the DOM but does NOT
    unmount it: the child instance, its scope effects and bindings stay live so
    re-show works WITHOUT a remount. This pins hide ≠ unmount — an if-hide must
    never trigger the recursive ``destroy()``."""
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
        items: list = state(default_factory=list)

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
    """``<ui-region>`` item removal routes through the full
    ``Component.destroy()`` — the contribution's scope effects are cleared, its
    DOM node is removed, the instance is marked destroyed and (via destroy's
    cascade) its nested children are unmounted."""
    from basis.plugins.regions.region import Region
    from basis.plugins.regions.registry import cls_path_of
    from basis.plugins.regions.store import RegionStore

    region_store = RegionStore("regions")
    region_store.__dict__["items"] = {}
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
# Mount-side contract: destroy()/on_unmounted()
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
    assert store._subscriptions == []


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
# Unmount path: region adopts full destroy, JsComponent
# boot-race guard, whole-loop cascade (tests only)
# ---------------------------------------------------------------------------

class LoggedLeaf(Component):
    """Nested template child of a region contribution; records ``on_unmounted``
    on a class-level log so tests can assert full-destroy recursion through a
    removed contribution."""

    __tag__ = "x-life-p2-logged-leaf"
    text = ""
    log: ClassVar[list[str]] = []

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
    log: ClassVar[list[str]] = []

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
    region_store.__dict__["items"] = {}
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
    region_store.__dict__["items"] = {}
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
        items: list = state(default_factory=list)

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


# ---------------------------------------------------------------------------
# Nested children declared in the class body
# ---------------------------------------------------------------------------

def _child_of(owner, cls):
    """The mounted child instance of *owner* whose class is *cls*."""
    return next(
        b.childinstance
        for b in owner.__bindings__
        if isinstance(b, ChildBinding) and isinstance(b.childinstance, cls)
    )


class _Panel(Component):
    """A component whose child is declared as a class in its own body."""

    __tag__ = "x-life-panel"

    class Body(Component):
        __tag__ = "x-life-panel-body"

        def template(self):
            """<div class="body">body</div>"""

    def template(self):
        """<section class="panel"><x-life-panel-body></x-life-panel-body></section>"""


def test_a_class_in_a_component_body_mounts_as_its_child():
    panel = _mount(_Panel)

    assert "panel" in panel.__element__.getAttribute("class")
    assert isinstance(_child_of(panel, _Panel.Body), _Panel.Body)


def test_nested_children_are_collected_when_the_class_is_defined():
    assert _Panel.__dict__["__nested_children__"] == (_Panel.Body,)


def test_the_nested_child_lookup_is_not_a_scan(monkeypatch):
    """``mount()`` asks each instance for them, so ``get_nested_children`` only reads what
    the class already knows. Re-deriving the answer per mount — an ``inspect`` walk of the
    class — is what made a loop of components cost O(n²)."""

    def rescan(cls):
        raise AssertionError("get_nested_children re-derived the answer")

    monkeypatch.setattr(_Panel, "_find_nested_children", classmethod(rescan))

    assert _Panel.get_nested_children() == (_Panel.Body,)
