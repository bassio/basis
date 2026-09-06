"""
Realistic benchmark scenarios for Basis (ROADMAP-PERFORMANCE.md, T0).

Each scenario is a :class:`~basis.benchmarks.harness.Scenario` with a fresh
``setup()`` (fixture) and a ``run(fixture)`` timed body. Scenarios deliberately
measure the *real* framework path the way an app hits it — e.g. component
mounting goes through ``Component.mount()`` (which, today, re-runs template
analysis per instance — exactly the cost T1 #11 / #15 target), and loop
rendering goes through the full LIS reconcile.

Isolation & side-effect notes
-----------------------------
* **No component classes are created at import time.** Every class is built by
  a factory called from ``setup()`` (untimed), so merely importing this module
  — e.g. from the CLI, or during pytest collection — registers nothing in the
  global component/store registries and cannot pollute other tests.
* Each ``setup`` clears the global registries and builds a *fresh* class + DOM,
  so one iteration never leaks into the next (store names, component tags,
  routers, pending subscriptions, blueprint state).
"""

from __future__ import annotations

import asyncio
import types
from typing import Any

from basis.benchmarks.harness import Scenario
from basis.shared.reactive import DependencyGraph, ReactiveScope

# ─────────────────────────────────────────────────────────────────────────
# Registry isolation
# ─────────────────────────────────────────────────────────────────────────


def _clear_registries() -> None:
    """Reset the global registries so benchmark iterations are isolated."""
    from basis.shared.store import Store
    from basis.shared.base_component import BaseComponent
    from basis.shared.router import Route

    Store._registry.clear()
    Store._pending_subscriptions.clear()
    Store._store_blueprints.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._pending_subscriptions.clear()
    Route._route_registry.clear()


def _rows(n: int) -> list[dict]:
    return [{"id": i, "name": f"row {i}"} for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────
# Component factories (called from setup — never at import time)
# ─────────────────────────────────────────────────────────────────────────

from basis.server.server_component import ServerComponent  # noqa: E402
from basis.shared.element import Element  # noqa: E402


def _make_card() -> type:
    """A representative dashboard "card": 4 text fields, 2 reactive class
    attributes, and a small tag loop — ~7 reactive bindings per instance."""

    class Card(ServerComponent):
        def template(self):
            """
            <div class="card-{tone}">
              <h3 class="title-{tone}">{title}</h3>
              <p class="body">{body}</p>
              <span class="count">{count}</span>
              <span class="label">{label}</span>
              <div for="tag" in="{tags}" class="tag">{tag}</div>
            </div>
            """

        tone = "default"
        title = ""
        body = ""
        count = 0
        label = ""
        tags: list = []

    return Card


def _mount_cards(container: Element, cls: type, n: int) -> None:
    """Mount ``n`` instances into ``container`` (the real mount path)."""
    for _ in range(n):
        cls.mount(container, replace=False)


def _make_form(m: int) -> type:
    """A component with ``m`` independent text bindings ``{f0}..{fm-1}`` and
    ``m`` class-default fields (so the initial force-react renders cleanly,
    with no eval-error noise)."""
    spans = "".join(f"<span>{{f{i}}}</span>" for i in range(m))
    defaults = {f"f{i}": 0 for i in range(m)}
    return type(
        f"Form{m}",
        (ServerComponent,),
        {"template": f"<div>{spans}</div>", "__module__": __name__, **defaults},
    )


def _make_table() -> type:
    """A 1-column table rendered from a keyed loop (the 1k/10k-row scenario)."""

    class Table(ServerComponent):
        def template(self):
            """
            <div>
              <div for="row" in="{rows}" key="id" class="row-{row['id']}">{row['name']}</div>
            </div>
            """

        rows: list = []

    return Table


def _make_ssr():
    """Root component (1k-row loop) + Page for the SSR-hydration scenario."""
    from basis.shared.page import Page

    class SsrRoot(ServerComponent):
        def template(self):
            """
            <div>
              <div for="row" in="{rows}" key="id">{row['name']}</div>
            </div>
            """

        rows = _rows(1000)

    class SsrPage(Page):
        root_component = SsrRoot
        title = "Basis Bench"
        entry_module = "/basis/client/entrypoint.py"

    return SsrRoot, SsrPage


# ─────────────────────────────────────────────────────────────────────────
# Scenario: mount N components
# ─────────────────────────────────────────────────────────────────────────


def _setup_mount(n: int) -> dict:
    _clear_registries()
    return {
        "cls": _make_card(),
        "container": Element("div", attrs={}, children=[]),
        "n": n,
    }


def _run_mount(fixture: dict) -> None:
    _mount_cards(fixture["container"], fixture["cls"], fixture["n"])


def _verify_mount(fixture: dict) -> None:
    # One card root per mount, appended to the container.
    assert len(fixture["container"].children) == fixture["n"]


SCENARIO_MOUNT_50 = Scenario(
    name="mount_50_components",
    desc="Mount 50 Card components (real mount path, ~7 bindings each)",
    scale="50 instances",
    setup=lambda: _setup_mount(50),
    run=_run_mount,
    verify=_verify_mount,
)

SCENARIO_MOUNT_200 = Scenario(
    name="mount_200_components",
    desc="Mount 200 Card components (real mount path, ~7 bindings each)",
    scale="200 instances",
    setup=lambda: _setup_mount(200),
    run=_run_mount,
    verify=_verify_mount,
)


# ─────────────────────────────────────────────────────────────────────────
# Scenario: mutate M state fields in one handler
# ─────────────────────────────────────────────────────────────────────────


def _setup_form(m: int) -> dict:
    _clear_registries()
    cls = _make_form(m)
    return {
        "cls": cls,
        "m": m,
        "instance": cls.mount(Element("div", attrs={}, children=[])),
    }


def _run_sequential(fixture: dict) -> None:
    """One handler mutating M fields sequentially — M separate DAG passes today
    (T1 #6: should become one implicit batch)."""
    m = fixture["m"]
    instance = fixture["instance"]
    for i in range(m):
        setattr(instance, f"f{i}", i + 1)


def _run_refrain(fixture: dict) -> None:
    """The same M-field mutation wrapped in one explicit ``refrain()`` batch —
    the current opt-in way to get a single DAG pass (T1 #6 makes it implicit)."""
    m = fixture["m"]
    instance = fixture["instance"]
    with instance.refrain() as r:
        for i in range(m):
            setattr(r, f"f{i}", i + 1)


def _verify_form(fixture: dict) -> None:
    # The handler writes f{i} = i+1; the last field must have landed.
    m = fixture["m"]
    assert getattr(fixture["instance"], f"f{m - 1}") == m


SCENARIO_MUTATE_SEQUENTIAL_10 = Scenario(
    name="mutate_10_fields_sequential",
    desc="One handler mutates 10 state fields sequentially (10 DAG passes)",
    scale="10 fields",
    setup=lambda: _setup_form(10),
    run=_run_sequential,
    verify=_verify_form,
)

SCENARIO_MUTATE_SEQUENTIAL_25 = Scenario(
    name="mutate_25_fields_sequential",
    desc="One handler mutates 25 state fields sequentially (25 DAG passes)",
    scale="25 fields",
    setup=lambda: _setup_form(25),
    run=_run_sequential,
    verify=_verify_form,
)

SCENARIO_MUTATE_BATCHED_10 = Scenario(
    name="mutate_10_fields_refrain",
    desc="One handler mutates 10 fields inside one refrain() batch",
    scale="10 fields (batched)",
    setup=lambda: _setup_form(10),
    run=_run_refrain,
    verify=_verify_form,
)


# ─────────────────────────────────────────────────────────────────────────
# Scenario: render a 1k / 10k-row loop
# ─────────────────────────────────────────────────────────────────────────


def _setup_table(n: int) -> dict:
    _clear_registries()
    cls = _make_table()
    return {
        "cls": cls,
        "n": n,
        "instance": cls.mount(Element("div", attrs={}, children=[])),
    }


def _loop_binding(instance):
    return next(b for b in instance.__bindings__ if type(b).__name__ == "LoopBinding")


def _run_loop(fixture: dict) -> None:
    fixture["instance"].rows = _rows(fixture["n"])


def _verify_loop(fixture: dict) -> None:
    # Setting `rows` triggers the LoopBinding effect; assert it reconciled.
    assert len(_loop_binding(fixture["instance"]).instances) == fixture["n"]


SCENARIO_LOOP_1K = Scenario(
    name="loop_render_1k",
    desc="Set a 1,000-row keyed list -> full LIS reconcile + per-item bindings",
    scale="1,000 rows",
    setup=lambda: _setup_table(1000),
    run=_run_loop,
    verify=_verify_loop,
)

SCENARIO_LOOP_10K = Scenario(
    name="loop_render_10k",
    desc="Set a 10,000-row keyed list -> full LIS reconcile + per-item bindings",
    scale="10,000 rows",
    setup=lambda: _setup_table(10000),
    run=_run_loop,
    verify=_verify_loop,
)


# ─────────────────────────────────────────────────────────────────────────
# Scenario: hydrate an SSR page
# ─────────────────────────────────────────────────────────────────────────

from basis.server.app import Basis  # noqa: E402


def _make_request(app) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        app=app,
        url=types.SimpleNamespace(
            path="/bench", scheme="http", netloc="test", query=""
        ),
    )


def _setup_ssr() -> dict:
    _clear_registries()
    from basis.server.render import render_page

    app = Basis()
    app.bootstrap()
    _root, page_cls = _make_ssr()
    return {"render_page": render_page, "request": _make_request(app), "page_cls": page_cls}


def _run_ssr(fixture: dict) -> None:
    asyncio.run(
        fixture["render_page"](fixture["request"], fixture["page_cls"], render_mode="ssr")
    )


def _verify_ssr(fixture: dict) -> None:
    # A cheap correctness proof: the rendered shell contains the last row and
    # the hydration markers (re-render once more — still untimed warm-up work).
    html = asyncio.run(
        fixture["render_page"](fixture["request"], fixture["page_cls"], render_mode="ssr")
    )
    assert "row 999" in html
    assert "data-basis" in html


SCENARIO_SSR_HYDRATE = Scenario(
    name="ssr_hydrate_1k",
    desc="Render an SSR page with a 1k-row root: mount + hydration IDs + serialize state",
    scale="1 page / 1k rows",
    setup=_setup_ssr,
    run=_run_ssr,
    verify=_verify_ssr,
)


# ─────────────────────────────────────────────────────────────────────────
# Scenario: fan-out a store to 50 subscribers
# ─────────────────────────────────────────────────────────────────────────


class _Subscriber:
    """A lightweight stand-in for a component subscribed to ``$store.attr``.

    Carries its own DAG + a reactive effect for the store field, so a store
    mutation genuinely cascades: store effect → ``sub.react([...])`` → the
    subscriber's own DAG effect runs (the same shape as a real binding).
    """

    _counter = 0

    def __init__(self, store_name: str, attr: str):
        self._dag = DependencyGraph()
        self._scope = ReactiveScope()
        key = f"${store_name}.{attr}"
        self._dag.get_or_create_state(key)
        _Subscriber._counter += 1
        self._dag.add_effect(f"sub_effect_{_Subscriber._counter}", self._noop, [key])

    @staticmethod
    def _noop() -> None:
        pass

    def react(self, names: list[str]) -> None:
        self._dag.trigger_batch(names)


def _setup_fanout(n: int) -> "Any":
    _clear_registries()
    from basis.shared.store import Store

    store = Store(f"fan_{n}")
    store.count = 0
    for _ in range(n):
        sub = _Subscriber(f"fan_{n}", "count")
        store.add_subscription(sub, "count", scope=None)
    return store


def _run_fanout(store) -> None:
    store.count = store.count + 1


def _verify_fanout(store) -> None:
    assert store.count == 1


SCENARIO_FANOUT_50 = Scenario(
    name="store_fanout_50",
    desc="Mutate one store field -> notify 50 subscribers (store->component edges)",
    scale="50 subscribers",
    setup=lambda: _setup_fanout(50),
    run=_run_fanout,
    verify=_verify_fanout,
)

SCENARIO_FANOUT_100 = Scenario(
    name="store_fanout_100",
    desc="Mutate one store field -> notify 100 subscribers (store->component edges)",
    scale="100 subscribers",
    setup=lambda: _setup_fanout(100),
    run=_run_fanout,
    verify=_verify_fanout,
)


# ─────────────────────────────────────────────────────────────────────────
# Scenario: template / expression parsing (T1 #1 / #3 baseline)
# ─────────────────────────────────────────────────────────────────────────

from basis.shared.expr import (  # noqa: E402
    ALLOWED_BUILTINS,
    extract_dependencies,
    safe_format,
)


class _TemplateCtx:
    a = "alpha"
    b = 2
    c = "gamma"


_TEMPLATE = "{a} #{b} {c}"


def _setup_template_parse() -> dict:
    _, trees = extract_dependencies(_TEMPLATE, ALLOWED_BUILTINS)
    return {"trees": trees, "ctx": _TemplateCtx()}


def _run_template_format(fixture: dict) -> None:
    # 1000 binding updates on a 3-field template — the current TextBinding hot
    # path (safe_format re-parses the template every update: T1 #1).
    for _ in range(1000):
        safe_format(
            _TEMPLATE,
            fixture["ctx"],
            ALLOWED_BUILTINS,
            ast_trees=fixture["trees"],
        )


def _run_template_parse(fixture: dict) -> None:
    # 1000 template analyses — blueprint-analysis cost for 1000 distinct
    # templates (T1 #1/#3: parse once at blueprint time, not per update).
    for _ in range(1000):
        extract_dependencies(_TEMPLATE, ALLOWED_BUILTINS)


def _verify_template(fixture: dict) -> None:
    assert safe_format(
        _TEMPLATE, fixture["ctx"], ALLOWED_BUILTINS, ast_trees=fixture["trees"]
    ) == "alpha #2 gamma"


SCENARIO_TEMPLATE_FORMAT = Scenario(
    name="template_format_1k",
    desc="1,000 safe_format updates on a 3-field template (T1 #1 hot path)",
    scale="1,000 updates",
    setup=_setup_template_parse,
    run=_run_template_format,
    verify=_verify_template,
)

SCENARIO_TEMPLATE_PARSE = Scenario(
    name="template_analyze_1k",
    desc="1,000 extract_dependencies analyses (T1 #1/#3 parse baseline)",
    scale="1,000 templates",
    setup=lambda: {"ctx": _TemplateCtx()},
    run=_run_template_parse,
)


# ─────────────────────────────────────────────────────────────────────────
# The suite
# ─────────────────────────────────────────────────────────────────────────

#: All scenarios, in a sensible display order.
SCENARIOS: list[Scenario] = [
    SCENARIO_MOUNT_50,
    SCENARIO_MOUNT_200,
    SCENARIO_MUTATE_SEQUENTIAL_10,
    SCENARIO_MUTATE_SEQUENTIAL_25,
    SCENARIO_MUTATE_BATCHED_10,
    SCENARIO_LOOP_1K,
    SCENARIO_LOOP_10K,
    SCENARIO_SSR_HYDRATE,
    SCENARIO_FANOUT_50,
    SCENARIO_FANOUT_100,
    SCENARIO_TEMPLATE_FORMAT,
    SCENARIO_TEMPLATE_PARSE,
]
