"""The responsive shell contract (``ROADMAP-MOBILE.md`` M1.4).

Two properties make the compact arrangement trustworthy, and each is asserted here:

* **one source.** The ``$device`` tier fields and the shell's ``@media`` rules answer
  the same query, both derived from ``basis.shared.breakpoints`` — layout reflow and the
  Python tier cannot drift apart.
* **no structural branching.** The arrangement is CSS, so the markup a server sends is
  the same at every viewport; only the stylesheet differs. (The browser lane,
  ``tests/browser/test_shell_responsive.py``, proves the layout that follows.)

Plus the parts' own compact contract: sizing travels as custom properties (so a media
query can restate it), the sidebar splits docked from drawer state, and the trigger
flips whichever state the viewport tier uses.
"""
import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import basis.plugins.shell.sidebar as sidebar_module
from basis.plugins.shell import (  # noqa: F401  (registers every shell custom element)
    ActivityBar,
    AppShell,
    Footer,
    Header,
    Main,
    MainContainer,
    Sidebar,
    SidebarLeft,
    SidebarRight,
    SidebarTrigger,
    SiteShell,
    Splitter,
    Stack,
    StatusBar,
    TabsBar,
    TitleBar,
    Workspace,
    plugin as shell_plugin,
)
from basis.server.app import Basis
from basis.shared.breakpoints import (
    COMPACT_MAX_WIDTH,
    MEDIUM_MAX_WIDTH,
    TIERS,
    compact_block,
    compact_media,
    compact_query,
    medium_media,
    medium_query,
)
from basis.shared.component import Component
from basis.shared.device import DeviceStore
from basis.shared.page import _synthesize_page
from basis.shared.store import Store

#: Every part that owns optional compact CSS.
RESPONSIVE_PARTS = (Stack, TitleBar, StatusBar, ActivityBar, Sidebar, Splitter)

#: Every part whose template must stay viewport-agnostic.
FRAME_PARTS = (
    AppShell,
    Workspace,
    Stack,
    TitleBar,
    StatusBar,
    ActivityBar,
    Sidebar,
    SidebarLeft,
    SidebarRight,
    MainContainer,
    TabsBar,
    Splitter,
    Header,
    Main,
    Footer,
    SiteShell,
)


@pytest.fixture(autouse=True)
def _clean_registries():
    saved_stores = dict(Store._registry)
    saved_routes = list(Basis._component_routes)
    yield
    Store._registry.clear()
    Store._registry.update(saved_stores)
    Basis._component_routes = saved_routes


def _app_with_shell():
    app = Basis()
    app.bootstrap()
    app.include_plugin(shell_plugin)
    return app


def _render(app, root_component, entry_module="/responsive_root.py"):
    app.include_page("/", page_cls=_synthesize_page(root_component, entry_module=entry_module))
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    return resp.text


def _initial_state(html: str) -> dict:
    payload = html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0]
    return json.loads(payload)


FRAME = """
<div class="root">
    <div class="app">
        <shell-title-bar height="48px">
            <shell-sidebar-trigger target="#sidebarLeft"></shell-sidebar-trigger>
        </shell-title-bar>
        <shell-stack direction="row" layout="workbench">
            <shell-activity-bar width="56px"></shell-activity-bar>
            <shell-sidebar-left id="sidebarLeft" width="240px"></shell-sidebar-left>
            <shell-splitter direction="horizontal"></shell-splitter>
            <shell-main-container></shell-main-container>
        </shell-stack>
        <shell-status-bar height="28px"></shell-status-bar>
    </div>
</div>
"""


def _frame_html():
    class Root(Component):
        template = FRAME

    return _render(_app_with_shell(), Root)


# ---------------------------------------------------------------------------
# The breakpoint contract: one source for the field and the stylesheet.
# ---------------------------------------------------------------------------

def test_both_forms_are_derived_from_the_boundary_constants():
    assert compact_query() == f"(max-width: {COMPACT_MAX_WIDTH}px)"
    assert medium_query() == (
        f"(min-width: {COMPACT_MAX_WIDTH + 1}px) and (max-width: {MEDIUM_MAX_WIDTH}px)"
    )
    assert compact_media() == f"@media {compact_query()}"
    assert medium_media() == f"@media {medium_query()}"
    assert TIERS == ("compact", "medium", "regular")


def test_compact_block_wraps_css_in_the_contract_query():
    wrapped = compact_block(".x { color: red }")

    assert wrapped.startswith(f"@media {compact_query()} {{")
    assert ".x { color: red }" in wrapped
    assert wrapped.endswith("}")


def test_every_responsive_part_emits_the_contract_query():
    """No part may hard-code a breakpoint that the tier fields do not share."""
    for cls in RESPONSIVE_PARTS:
        assert f"@media {compact_query()}" in cls._get_style_string(), cls.__name__


# ---------------------------------------------------------------------------
# The viewport tier.
# ---------------------------------------------------------------------------

def test_tier_is_derived_from_the_two_declared_queries():
    device = DeviceStore("device")

    assert device.tier == "regular"          # the neutral both sides start from
    device.compact = True
    assert device.tier == "compact"
    device.compact = False
    device.medium = True
    assert device.tier == "medium"
    device.medium = False
    assert device.tier == "regular"


def test_tier_neutrals_serialise_into_the_initial_state():
    state = _initial_state(_frame_html())

    assert state["device"]["compact"] is False
    assert state["device"]["medium"] is False


def test_templates_can_read_the_tier_and_stay_neutral_on_the_server():
    class Root(Component):
        template = """
        <div class="root">
            <span class="tier">{$device.tier}</span>
            <span class="narrow" if="{$device.compact}">narrow</span>
        </div>
        """

    html = _render(_app_with_shell(), Root)

    # The server renders the neutral tier; the browser corrects it after mount, which
    # is why the tier may drive behaviour but never structure.
    assert 'class="tier"' in html
    assert ">regular</span>" in html
    assert 'class="narrow"' not in html


def test_frame_templates_never_branch_on_the_viewport():
    """The arrangement is CSS: no part's markup may depend on the viewport."""
    for cls in FRAME_PARTS:
        template = cls.template.__doc__ or ""
        assert "device" not in template, cls.__name__
        assert "tier" not in template, cls.__name__


# ---------------------------------------------------------------------------
# The arrangement hook.
# ---------------------------------------------------------------------------

def test_stack_renders_the_layout_mode():
    class Root(Component):
        template = """
        <div class="root">
            <shell-stack direction="row" layout="workbench"></shell-stack>
            <shell-stack direction="row"></shell-stack>
        </div>
        """

    html = _render(_app_with_shell(), Root)

    assert 'data-layout="workbench"' in html
    assert 'data-layout="none"' in html


def test_workbench_mode_restacks_the_frame():
    css = Stack._get_style_string()

    assert '.shell-stack[data-layout="workbench"]' in css
    assert "flex-direction: column" in css.split('.shell-stack[data-layout="workbench"]', 1)[1]


def test_parts_rank_themselves_inside_a_workbench_frame():
    """The surface comes first and the rail last; each part owns its rank."""
    assert (
        '.shell-stack[data-layout="workbench"] > shell-main-container > .shell-main-container'
        in MainContainer._get_style_string()
    )
    assert "order: 1;" in MainContainer._get_style_string()

    assert (
        '.shell-stack[data-layout="workbench"] > shell-activity-bar > .shell-activity-bar'
        in ActivityBar._get_style_string()
    )
    assert "order: 2;" in ActivityBar._get_style_string()


def test_the_composed_workspace_declares_the_workbench_arrangement():
    html = _render(_app_with_shell(), Workspace)

    assert 'data-layout="workbench"' in html


# ---------------------------------------------------------------------------
# Sizing travels as custom properties (the precondition for any override).
# ---------------------------------------------------------------------------

def test_parts_size_themselves_with_custom_properties():
    html = _frame_html()

    for var in (
        "--shell-titlebar-height: 48px",
        "--shell-activitybar-width: 56px",
        "--sidebar-expanded: 240px",
        "--shell-splitter-size: 4px",
        "--shell-statusbar-height: 28px",
        "--stack-size: 1 1 auto",
    ):
        assert var in html, var


def test_no_shell_part_writes_layout_inline():
    """Inline layout would out-rank every stylesheet rule, compact rules included."""
    html = _frame_html()

    assert 'style="flex' not in html
    assert "--shell-titlebar-mobile-height: 44px" in html
    assert "--sidebar-mobile-width: min(85vw, 320px)" in html


# ---------------------------------------------------------------------------
# The chrome parts at compact width.
# ---------------------------------------------------------------------------

def test_title_bar_keeps_a_compact_height_rule():
    css = TitleBar._get_style_string()

    assert "flex: 0 0 var(--shell-titlebar-height, 48px)" in css
    assert "flex: 0 0 var(--shell-titlebar-mobile-height, 44px)" in css


def test_activity_bar_becomes_the_bottom_navigation():
    css = ActivityBar._get_style_string()

    # The rail's inner column steps out of the box tree so the icon groups become
    # items of the bar itself, which turns into a row.
    assert ".shell-activity-bar > .shell-stack" in css
    assert "flex: 0 0 var(--shell-activitybar-mobile-height, 52px)" in css
    assert "padding-bottom: var(--safe-area-bottom" in css


def test_status_bar_is_hidden_by_default_and_slims_on_request():
    class Hidden(Component):
        template = '<div class="root"><shell-status-bar></shell-status-bar></div>'

    class Slim(Component):
        template = (
            '<div class="root">'
            '<shell-status-bar mobile="slim"></shell-status-bar>'
            "</div>"
        )

    assert 'data-mobile="hidden"' in _render(_app_with_shell(), Hidden)
    assert 'data-mobile="slim"' in _render(_app_with_shell(), Slim, "/responsive_slim.py")

    css = StatusBar._get_style_string()
    assert '.shell-status-bar[data-mobile="hidden"]' in css
    assert '.shell-status-bar[data-mobile="slim"]' in css


def test_splitter_is_dropped_at_compact():
    compact = Splitter._get_style_string().split(compact_media(), 1)[1]

    assert ".shell-splitter {" in compact
    assert "display: none;" in compact


# ---------------------------------------------------------------------------
# The drawer.
# ---------------------------------------------------------------------------

def _trigger(target: str):
    trigger = SidebarTrigger()
    trigger.target = target
    return trigger


def _install_trigger_env(monkeypatch, sidebar_state, *, compact: bool):
    """A fake client DOM whose target host carries a component instance."""

    class FakeHost:
        pass

    FakeHost.__basis_instance__ = sidebar_state

    class FakeDocument:
        def querySelector(self, selector):
            return FakeHost()

    monkeypatch.setattr(sidebar_module, "IS_CLIENT", True)
    monkeypatch.setattr(sidebar_module, "document", FakeDocument())
    Store._registry["device"] = SimpleNamespace(compact=compact)


def test_sidebar_drawer_is_closed_by_default():
    class Root(Component):
        template = '<div class="root"><shell-sidebar side="left"></shell-sidebar></div>'

    html = _render(_app_with_shell(), Root)

    assert 'data-drawer="closed"' in html
    assert 'data-state="expanded"' in html


def test_sidebar_open_prop_drives_the_drawer_state():
    class Root(Component):
        template = """
        <div class="root">
            <shell-sidebar side="left" open="{is_open}"></shell-sidebar>
        </div>
        """
        is_open = True

    html = _render(_app_with_shell(), Root)

    assert 'data-drawer="open"' in html


def test_compact_sidebar_leaves_the_flow_and_paints_its_backdrop():
    css = Sidebar._get_style_string()
    compact = css.split(compact_media(), 1)[1]

    assert "position: fixed" in compact
    assert 'calc(-1 * var(--sidebar-mobile-width' in compact
    assert '.shell-sidebar[data-drawer="open"]::after' in compact
    # The backdrop sits behind the panel: the surface is the inner stack.
    assert ".shell-sidebar > .shell-stack" in css


def test_backdrop_click_closes_the_drawer_only_on_the_root():
    sidebar = Sidebar()
    root = object()
    panel_child = object()
    sidebar.__dict__["_element"] = root

    class Event:
        def __init__(self, target):
            self.target = target

    sidebar.open = True
    sidebar.on_backdrop_click(Event(panel_child))
    assert sidebar.open is True  # a tap inside the panel leaves it open

    sidebar.on_backdrop_click(Event(root))
    assert sidebar.open is False


def test_trigger_flips_the_drawer_state_at_the_compact_tier(monkeypatch):
    state = SimpleNamespace(open=False, collapsed=False)
    _install_trigger_env(monkeypatch, state, compact=True)

    _trigger("#sidebarLeft").toggle_sidebar(None)

    assert state.open is True
    assert state.collapsed is False  # the docked state is not the one on a phone


def test_trigger_flips_the_docked_state_on_a_regular_viewport(monkeypatch):
    state = SimpleNamespace(open=False, collapsed=False)
    _install_trigger_env(monkeypatch, state, compact=False)

    _trigger("#sidebarLeft").toggle_sidebar(None)

    assert state.collapsed is True
    assert state.open is False


def test_trigger_ignores_targets_that_are_not_components(monkeypatch):
    class PlainHost:
        """A host element with no Basis instance behind it."""

    class FakeDocument:
        def querySelector(self, selector):
            return PlainHost()

    monkeypatch.setattr(sidebar_module, "IS_CLIENT", True)
    monkeypatch.setattr(sidebar_module, "document", FakeDocument())
    Store._registry["device"] = SimpleNamespace(compact=True)

    # A target that is not a Basis component — or no target at all — is a no-op.
    _trigger("#sidebarLeft").toggle_sidebar(None)
    _trigger("").toggle_sidebar(None)
