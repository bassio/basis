"""
Shell plugin (P1) tests — ROADMAP-SHELL.md §10 (simplified slot-based design).

Covers: plugin registration (name, requires=[], static mount) + VFS serving of
the shell files; the ``Stack`` primitive (slotted children); the ``Splitter``
gated by a ``resizeable`` flag (present/absent); each chrome part rendering with
its props (height/width/border); the ``Workspace`` band (sidebars + splitters +
main container); and the ``AppShell`` frame with snake_case prop pass-through.

NOTE: the shell plugin is auto-discovered in the test suite (its entry point is
registered in the installed dist metadata), but every test includes it explicitly
anyway — ``include_plugin`` is idempotent by name, so the explicit include makes
the plugin under test unambiguous regardless of discovery.
"""
import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.page import _synthesize_page
from basis.shared.component import Component

# Registers every shell custom element + exposes the plugin instance.
from basis.plugins.shell import (
    plugin as shell_plugin,
    Stack,
    Splitter,
    ActivityBar,
    AppShell,
    TitleBar,
    StatusBar,
    Workspace,
    Sidebar,
    SidebarLeft,
    SidebarRight,
    SidebarTrigger,
    MainContainer,
    TabsBar,
    Header,
    Main,
    Footer,
    SiteShell,
)

# Registers the <ui-icon> custom element used inside the activity bar.
import basis.plugins.ui.icon.icon  # noqa: F401


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes


def _app_with_shell():
    """A bootstrapped app with the shell plugin explicitly included."""
    app = Basis()
    app.bootstrap()
    app.include_plugin(shell_plugin)
    return app


def _render(app, root_component, entry_module):
    app.include_page("/", page_cls=_synthesize_page(root_component, entry_module=entry_module))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    return resp.text


# ---------------------------------------------------------------------------
# Plugin registration + static serving.
# ---------------------------------------------------------------------------

def test_plugin_registers_and_serves_static_mount():
    app = _app_with_shell()

    assert shell_plugin.name == "shell"
    assert shell_plugin.requires == ["theme"]  # shell chrome is token-only (ROADMAP-THEMING)
    assert shell_plugin._app is app

    mounts = [getattr(r, "path", None) for r in app._component_routes]
    assert "/basis/plugins/shell" in mounts

    # Every shell component module is served to the client (isomorphic VFS).
    for mod in (
        "basis.plugins.shell.stack",
        "basis.plugins.shell.splitter",
        "basis.plugins.shell.activity_bar",
        "basis.plugins.shell.title_bar",
        "basis.plugins.shell.status_bar",
        "basis.plugins.shell.sidebar",
        "basis.plugins.shell.main_container",
        "basis.plugins.shell.tabs_bar",
        "basis.plugins.shell.workspace",
        "basis.plugins.shell.app_shell",
        "basis.plugins.shell.site",
        "basis.plugins.shell.plugin",
    ):
        assert mod in app.vfs.client_modules


# ---------------------------------------------------------------------------
# Stack primitive.
# ---------------------------------------------------------------------------

def test_stack_renders_slotted_children_ssr():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-stack direction="row" gap="4px">
                <span class="chip">a</span>
                <span class="chip">b</span>
            </shell-stack>
        </div>
        """

    html = _render(app, Root, "/test_stack.py")
    assert 'class="shell-stack"' in html
    assert html.count('class="chip"') == 2


# ---------------------------------------------------------------------------
# Splitter gated by the resizeable flag.
# ---------------------------------------------------------------------------

def test_splitter_renders_between_components_when_resizeable():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-stack direction="row">
                <shell-sidebar-left width="240px"></shell-sidebar-left>
                <shell-splitter if="{flag}" direction="horizontal"></shell-splitter>
                <shell-main-container></shell-main-container>
            </shell-stack>
        </div>
        """
        flag = True

    html = _render(app, Root, "/test_splitter.py")
    assert html.count("<shell-splitter") == 1
    assert "<shell-sidebar-left" in html
    assert 'class="shell-sidebar"' in html
    assert 'class="shell-main-container"' in html


def test_splitter_absent_when_not_resizeable():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-stack direction="row">
                <shell-sidebar-left width="240px"></shell-sidebar-left>
                <shell-splitter if="{flag}" direction="horizontal"></shell-splitter>
                <shell-main-container></shell-main-container>
            </shell-stack>
        </div>
        """
        flag = False

    html = _render(app, Root, "/test_splitter_off.py")
    assert "<shell-splitter" not in html
    assert "<shell-sidebar-left" in html
    assert 'class="shell-sidebar"' in html
    assert 'class="shell-main-container"' in html


# ---------------------------------------------------------------------------
# Sidebar (single component, side prop) + collapse + trigger.
# ---------------------------------------------------------------------------

def test_sidebar_expanded_by_default():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-sidebar side="right"></shell-sidebar>
        </div>
        """

    html = _render(app, Root, "/test_sidebar_expanded.py")
    assert 'class="shell-sidebar"' in html
    assert 'data-side="right"' in html
    assert 'data-state="expanded"' in html


def test_sidebar_collapsed_renders_data_state():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-sidebar side="left" collapsed="{flag}"></shell-sidebar>
        </div>
        """
        flag = True

    html = _render(app, Root, "/test_sidebar_collapsed.py")
    assert 'class="shell-sidebar"' in html
    assert 'data-side="left"' in html
    assert 'data-state="collapsed"' in html


def test_sidebar_collapsible_icon_renders_data_attr():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-sidebar side="left" collapsible="icon" collapsed="{flag}"></shell-sidebar>
        </div>
        """
        flag = True

    html = _render(app, Root, "/test_sidebar_icon.py")
    assert 'data-collapsible="icon"' in html
    assert 'data-state="collapsed"' in html


def test_sidebar_left_distinct_tag_inherits_collapse():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-sidebar-left collapsed="{flag}"></shell-sidebar-left>
        </div>
        """
        flag = True

    html = _render(app, Root, "/test_sidebar_left_tag.py")
    assert "<shell-sidebar-left" in html
    assert 'class="shell-sidebar"' in html
    assert 'data-side="left"' in html
    assert 'data-state="collapsed"' in html


def test_sidebar_trigger_renders_button():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-sidebar-trigger target="#sidebarRight"></shell-sidebar-trigger>
        </div>
        """

    html = _render(app, Root, "/test_sidebar_trigger.py")
    assert 'class="shell-sidebar-trigger"' in html
    assert 'title="Toggle sidebar"' in html


# ---------------------------------------------------------------------------
# Site (document-flow) layout — Header / Main / Footer / SiteShell.
# ---------------------------------------------------------------------------

def test_site_shell_renders_header_main_footer():
    app = _app_with_shell()

    html = _render(app, SiteShell, "/test_site.py")
    assert 'class="shell-site"' in html
    assert "<header" in html
    assert 'class="shell-header"' in html
    assert "<main" in html
    assert 'class="shell-main"' in html
    assert "<footer" in html
    assert 'class="shell-footer"' in html


def test_site_shell_uses_document_flow_min_height():
    app = _app_with_shell()

    html = _render(app, SiteShell, "/test_site_flow.py")
    assert "min-height: 100vh" in html


def test_site_shell_sticky_header_pass_through():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-site sticky_header="{flag}"></shell-site>
        </div>
        """
        flag = True

    html = _render(app, Root, "/test_site_sticky.py")
    assert 'data-sticky="True"' in html


def test_header_sticky_from_python_bool():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-header sticky="{flag}"></shell-header>
        </div>
        """
        flag = True

    html = _render(app, Root, "/test_header_sticky.py")
    assert 'class="shell-header"' in html
    assert 'data-sticky="True"' in html


def test_main_grows_to_fill():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-main></shell-main>
        </div>
        """

    html = _render(app, Root, "/test_main.py")
    assert 'class="shell-main"' in html
    assert "flex: 1 1 auto" in html


# ---------------------------------------------------------------------------
# Activity bar + icon.
# ---------------------------------------------------------------------------

def test_activity_bar_renders_top_and_bottom_slots():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-activity-bar width="56px">
                <ui-icon slot="top" content="📁" title="Explorer" view="teams" active="{flag}"></ui-icon>
                <ui-icon slot="top" content="🔍" title="Search"></ui-icon>
                <ui-icon slot="bottom" content="⚙" title="Settings"></ui-icon>
            </shell-activity-bar>
        </div>
        """
        flag = True

    html = _render(app, Root, "/test_activitybar.py")
    assert 'class="shell-activity-bar"' in html
    assert "flex: 0 0 56px" in html
    # Both groups render, and each named slot received its content.
    assert 'class="shell-activity-top"' in html
    assert 'class="shell-activity-bottom"' in html
    # The ui-icons landed in the slots (tooltip + active state present).
    assert 'title="Explorer"' in html
    assert 'title="Settings"' in html
    assert 'class="ui-icon active"' in html


# ---------------------------------------------------------------------------
# Chrome parts render with their props.
# ---------------------------------------------------------------------------

def test_title_bar_renders_height_and_border():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-title-bar height="64px" border="none"></shell-title-bar>
        </div>
        """

    html = _render(app, Root, "/test_titlebar.py")
    assert 'class="shell-title-bar"' in html
    assert "flex: 0 0 64px" in html
    assert 'data-border="none"' in html


def test_parts_render_with_props():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-status-bar height="30px"></shell-status-bar>
            <shell-sidebar-right width="200px" border="left"></shell-sidebar-right>
            <shell-tabs-bar height="40px"></shell-tabs-bar>
            <shell-main-container></shell-main-container>
        </div>
        """

    html = _render(app, Root, "/test_parts.py")
    assert 'class="shell-status-bar"' in html
    assert "flex: 0 0 30px" in html
    assert "<shell-sidebar-right" in html
    assert 'class="shell-sidebar"' in html
    assert "--sidebar-expanded: 200px" in html
    assert 'data-border="left"' in html
    assert 'class="shell-tabs-bar"' in html
    assert "flex: 0 0 40px" in html
    assert 'class="shell-main-container"' in html


# ---------------------------------------------------------------------------
# Workspace band + AppShell frame.
# ---------------------------------------------------------------------------

def test_workspace_renders_sidebars_splitters_and_main():
    app = _app_with_shell()

    html = _render(app, Workspace, "/test_workspace.py")
    assert 'class="shell-workspace"' in html
    assert 'class="shell-activity-bar"' in html
    assert "<shell-sidebar-left" in html
    assert "<shell-sidebar-right" in html
    assert html.count('class="shell-sidebar"') == 2
    assert 'data-side="left"' in html
    assert 'data-side="right"' in html
    assert 'class="shell-main-container"' in html
    # Both sidebars resizeable by default → two splitters.
    assert html.count("<shell-splitter") == 2


def test_workspace_skips_splitter_when_sidebar_not_resizeable():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-workspace sidebar_left_resizeable="{flag}"></shell-workspace>
        </div>
        """
        flag = False

    html = _render(app, Root, "/test_workspace_off.py")
    assert html.count("<shell-splitter") == 1
    # The sidebar is still present (just not flanked by a splitter).
    assert "<shell-sidebar-left" in html
    assert 'class="shell-sidebar"' in html
    assert 'data-side="left"' in html


def test_app_shell_renders_full_frame_with_prop_pass_through():
    app = _app_with_shell()

    class Root(Component):
        """
        <div class="root">
            <shell-app sidebar_left_width="320px" titlebar_height="64px"></shell-app>
        </div>
        """

    html = _render(app, Root, "/test_appshell.py")
    assert 'class="shell-app"' in html
    assert 'class="shell-title-bar"' in html
    assert 'class="shell-workspace"' in html
    assert 'class="shell-activity-bar"' in html
    assert 'class="shell-status-bar"' in html
    # snake_case attrs pass through: AppShell → Workspace → Sidebar width.
    assert "--sidebar-expanded: 320px" in html
    assert "flex: 0 0 64px" in html


def test_app_shell_renders_all_parts_as_components():
    # The parts are real component classes with the expected tags.
    assert AppShell.__tag__ == "shell-app"
    assert TitleBar.__tag__ == "shell-title-bar"
    assert StatusBar.__tag__ == "shell-status-bar"
    assert Workspace.__tag__ == "shell-workspace"
    assert ActivityBar.__tag__ == "shell-activity-bar"
    assert Sidebar.__tag__ == "shell-sidebar"
    assert SidebarLeft.__tag__ == "shell-sidebar-left"
    assert SidebarRight.__tag__ == "shell-sidebar-right"
    assert SidebarTrigger.__tag__ == "shell-sidebar-trigger"
    assert MainContainer.__tag__ == "shell-main-container"
    assert TabsBar.__tag__ == "shell-tabs-bar"
    assert Header.__tag__ == "shell-header"
    assert Main.__tag__ == "shell-main"
    assert Footer.__tag__ == "shell-footer"
    assert SiteShell.__tag__ == "shell-site"
    assert Splitter.__tag__ == "shell-splitter"
    assert Stack.__tag__ == "shell-stack"
