"""Render the full `.j2` template set for canonical configs — P1 of INIT-SHELL-PLAN.md.

The P1 gate: every generated file exists with the right content, and the
context-coverage guard proves every template renders without `StrictUndefined`
raising (i.e. every key a template uses is provided by `layout.build_context`).
"""

from __future__ import annotations

import re

import pytest

from basis.cli.init.config import PARADIGM_APP, PARADIGM_SITE, ShellConfig
from basis.cli.init.layout import build_context, build_inventory, dest_path
from basis.cli.init.render import render_template
from basis.cli.init.writer import generate


# --- helpers --------------------------------------------------------------

def _render_all(config: ShellConfig) -> dict[str, str]:
    """Render every applicable template for ``config`` -> {dest: content}."""
    ctx = build_context(config)
    return {
        dest_path(t, config): render_template(t.source, ctx)
        for t in build_inventory(config)
    }


def _canonical_app() -> ShellConfig:
    return ShellConfig(
        project_name="myapp",
        titlebar=True,
        statusbar=True,
        activitybar=True,
        sidebar_left=True,
        sidebar_right=False,
        demo=True,
        example_store=True,
        example_plugin=True,
    )


# --- context-coverage guard ------------------------------------------------

def test_context_covers_maximally_enabled_configs():
    """Every template renders for the max-enabled config of each paradigm."""
    for cfg in (
        ShellConfig(project_name="x", paradigm=PARADIGM_APP, titlebar=True,
                    statusbar=True, activitybar=True, sidebar_left=True,
                    sidebar_right=True, demo=True,
                    example_store=True, example_plugin=True),
        ShellConfig(project_name="y", paradigm=PARADIGM_SITE, header=True,
                    footer=True, sticky_header=True, demo=True,
                    example_store=True, example_plugin=True),
    ):
        files = _render_all(cfg)
        assert files


def test_context_covers_minimal_config():
    """Every template renders for the all-off config (else branches)."""
    cfg = ShellConfig(project_name="z", titlebar=False, statusbar=False,
                      activitybar=False, sidebar_left=False, sidebar_right=False,
                      demo=False, example_store=False,
                      example_plugin=False)
    files = _render_all(cfg)
    assert files


# --- writer / project tree ------------------------------------------------

def test_generate_writes_full_project_tree(tmp_path):
    written = generate(_canonical_app(), tmp_path)
    dests = {str(p.relative_to(tmp_path)) for p in written}
    expected = {
        "pyproject.toml",
        "src/myapp/__init__.py",
        "src/myapp/components/page.py",
        "src/myapp/README.md",
        ".gitignore",
        "src/myapp/components/__init__.py",
        "src/myapp/components/app_container.py",
        "src/myapp/components/titlebar.py",
        "src/myapp/components/statusbar.py",
        "src/myapp/components/activitybar.py",
        "src/myapp/components/sidebar.py",
        "src/myapp/stores/__init__.py",
        "src/myapp/stores/app_state.py",
        "src/myapp/plugins/__init__.py",
        "src/myapp/plugins/demo.py",
        "src/myapp/static/app.css",
    }
    assert expected <= dests


def test_generated_init_registers_ssr_page(tmp_path):
    generate(_canonical_app(), tmp_path)
    init = (tmp_path / "src/myapp/__init__.py").read_text()
    assert "app = Basis()" in init
    assert "app.bootstrap()" in init
    assert "from myapp.components.page import HomePage" in init
    assert 'app.serve("/")(HomePage)' in init


def test_generated_init_mounts_static(tmp_path):
    generate(_canonical_app(), tmp_path)
    init = (tmp_path / "src/myapp/__init__.py").read_text()
    assert "include_components_dir(" in init
    assert '"/static"' in init
    assert 'name="app_static"' in init


def test_generated_page_has_root_component(tmp_path):
    generate(_canonical_app(), tmp_path)
    page = (tmp_path / "src/myapp/components/page.py").read_text()
    assert "class HomePage(Page):" in page
    assert "root_component = AppContainer" in page


def test_generated_page_links_app_css(tmp_path):
    generate(_canonical_app(), tmp_path)
    page = (tmp_path / "src/myapp/components/page.py").read_text()
    assert 'stylesheets = ("/static/app.css",)' in page


def test_generated_store_seeds_theme(tmp_path):
    generate(_canonical_app(), tmp_path)
    store = (tmp_path / "src/myapp/stores/app_state.py").read_text()
    assert "class AppTheme(ThemeStore):" in store
    assert "self.dark_mode = True" in store  # canonical app uses the "dark" seed


def test_generated_store_seeds_light_theme(tmp_path):
    generate(ShellConfig(project_name="lite", theme="light"), tmp_path)
    store = (tmp_path / "src/lite/stores/app_state.py").read_text()
    assert "self.dark_mode = False" in store


def test_pyproject_uses_slug_and_name(tmp_path):
    generate(_canonical_app(), tmp_path)
    pyproject = (tmp_path / "pyproject.toml").read_text()
    assert 'name = "myapp"' in pyproject
    assert 'packages = ["src/myapp"]' in pyproject


# --- frame composition (app paradigm) --------------------------------------

def test_app_frame_includes_chosen_parts(tmp_path):
    generate(_canonical_app(), tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "<shell-title-bar" in frame
    assert "<shell-status-bar" in frame
    assert "<shell-activity-bar" in frame
    assert "<shell-sidebar-left" in frame
    assert "<shell-splitter" in frame
    assert "<shell-sidebar-right" not in frame  # sidebar_right=False
    assert "<shell-tabs-bar" not in frame


def test_app_frame_omits_unchosen_parts(tmp_path):
    cfg = ShellConfig(project_name="myapp", titlebar=False, statusbar=False,
                      activitybar=False, sidebar_left=False, sidebar_right=False)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "<shell-title-bar" not in frame
    assert "<shell-status-bar" not in frame
    assert "<shell-activity-bar" not in frame
    assert "<shell-sidebar-left" not in frame


def test_app_frame_includes_sidebar_right_when_requested(tmp_path):
    cfg = ShellConfig(project_name="myapp", sidebar_right=True)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "<shell-sidebar-right" in frame


# --- frame composition (site paradigm) -------------------------------------

def test_site_frame_uses_document_flow(tmp_path):
    cfg = ShellConfig(project_name="mysite", paradigm=PARADIGM_SITE,
                      header=True, footer=True, sticky_header=False)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/mysite/components/app_container.py").read_text()
    assert "<shell-site>" in frame
    assert "<shell-header" in frame
    assert "<shell-main>" in frame
    assert "<shell-footer" in frame
    assert "<shell-title-bar" not in frame
    assert "sticky_header = False" in frame


def test_site_frame_imports_shell_site(tmp_path):
    """The site frame composes <shell-site>/<shell-header>/<shell-main>/
    <shell-footer> directly, so it must import the module that registers them
    (else client hydration raises KeyError on those tags)."""
    cfg = ShellConfig(project_name="mysite", paradigm=PARADIGM_SITE)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/mysite/components/app_container.py").read_text()
    assert "import basis.plugins.shell.site" in frame


# --- demo / extras gating -------------------------------------------------

def test_no_demo_drops_demo_blocks(tmp_path):
    cfg = ShellConfig(project_name="myapp", demo=False)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "Increment" not in frame
    assert "demo-hero" not in frame
    assert "def increment" not in frame


def test_no_store_drops_store_demo_and_file(tmp_path):
    cfg = ShellConfig(project_name="myapp", demo=True, example_store=False)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "$app_state" not in frame
    assert "def add_item" not in frame
    assert (tmp_path / "src/myapp/stores/app_state.py").exists() is False


def test_no_plugin_drops_region_and_plugin(tmp_path):
    cfg = ShellConfig(project_name="myapp", example_plugin=False)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "ui-region" not in frame
    assert (tmp_path / "src/myapp/plugins/demo.py").exists() is False


def test_demo_plugin_contributes_region_view(tmp_path):
    generate(_canonical_app(), tmp_path)
    plugin = (tmp_path / "src/myapp/plugins/demo.py").read_text()
    assert "BasisPlugin(" in plugin
    assert 'serving_mount="/myapp/plugins"' in plugin
    assert 'plugin.add_to_region("workspace-center", DemoView)' in plugin
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert '<ui-region name="workspace-center">' in frame


# --- frame must import the modules registering its custom elements ---------

def test_app_frame_imports_ui_components_it_references(tmp_path):
    """The frame uses <ui-toast-container>/<ui-theme-provider>, so it must import
    the modules that register them (else SSR raises KeyError on those tags)."""
    generate(_canonical_app(), tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "import basis.plugins.theme" in frame
    assert "import basis.plugins.ui.toast.toast" in frame


def test_frame_ui_imports_survive_no_store(tmp_path):
    """<ui-theme-provider> is unconditional in the frame, so the theme import must
    not be gated behind the example-store option."""
    cfg = ShellConfig(project_name="myapp", example_store=False)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "<ui-theme-provider>" in frame
    assert "import basis.plugins.theme" in frame
    assert "<ui-toast-container>" in frame
    assert "import basis.plugins.ui.toast.toast" in frame


# --- shell frame layout (app = fixed 100vh viewport, site = document flow) --

def test_app_frame_is_fixed_viewport_flex_column(tmp_path):
    """The app shell must fill 100vh as a flex column so the status bar is
    pinned to the bottom edge (not floating after the content), with body
    margin reset and no page-level scroll."""
    generate(_canonical_app(), tmp_path)
    frame = (tmp_path / "src/myapp/components/app_container.py").read_text()
    assert "body { margin: 0; overflow: hidden; }" in frame
    assert "display: flex;" in frame
    assert "flex-direction: column;" in frame
    assert "height: 100vh;" in frame


def test_site_frame_is_scrollable_document_flow(tmp_path):
    """The site shell must stay in normal document flow (scrollable), with the
    body margin reset but NO 100vh overflow lock."""
    cfg = ShellConfig(project_name="mysite", paradigm=PARADIGM_SITE)
    generate(cfg, tmp_path)
    frame = (tmp_path / "src/mysite/components/app_container.py").read_text()
    assert "body { margin: 0; }" in frame
    assert "min-height: 100vh;" in frame
    assert "body { margin: 0; overflow: hidden; }" not in frame
    # No FIXED 100vh lock (min-height: 100vh is fine — the lookbehind skips it).
    assert not re.search(r"(?<!min-)height: 100vh;", frame)
    assert "overflow: hidden;" not in frame


# --- chrome parts are self-editable ----------------------------------------

def test_chrome_parts_carry_editable_templates(tmp_path):
    """Each generated chrome part is a self-editable starting point: it keeps the
    shell tag (no `__tag__` override — inherit + replace) but includes a
    `template()` docstring copy of the shell's, so the user can edit the markup
    without opening the framework."""
    cfg = ShellConfig(project_name="myapp")
    generate(cfg, tmp_path)
    for name in ["titlebar", "statusbar", "activitybar", "sidebar"]:
        part = (tmp_path / f"src/myapp/components/{name}.py").read_text()
        assert "def template(self):" in part, name
        assert "__tag__" not in part, name  # inherit the shell tag, don't redefine
        assert "<slot" in part, name  # bare or named (activity bar uses named slots)


# --- generated source is syntactically valid ------------------------------

def test_generated_python_files_compile(tmp_path):
    """The generated .py files parse (py_compile) — no Jinja leakage or bad Python."""
    import py_compile

    generate(_canonical_app(), tmp_path)
    for py_file in sorted((tmp_path / "src/myapp").rglob("*.py")):
        py_compile.compile(str(py_file), doraise=True)
