"""The Jinja2-based template renderer + layout context — P0 of INIT-SHELL-PLAN.md §4.9."""

from __future__ import annotations

import pytest
from jinja2 import UndefinedError

from basis.cli.init.config import PARADIGM_SITE, ShellConfig
from basis.cli.init.layout import build_context, build_inventory, dest_path
from basis.cli.init.render import render_string


# --- renderer (render_string) ---------------------------------------------

def test_interpolates_context_values():
    assert render_string("Hello {{ name }}!", {"name": "World"}) == "Hello World!"


def test_unknown_variable_fails_loud():
    with pytest.raises(UndefinedError, match="demo"):
        render_string("{{ demo }}", {"other": True})


def test_if_branch_included_when_truthy():
    t = "{% if demo %}yes{% endif %}"
    assert render_string(t, {"demo": True}) == "yes"
    assert render_string(t, {"demo": False}) == ""


def test_if_else():
    t = "{% if demo %}yes{% else %}no{% endif %}"
    assert render_string(t, {"demo": False}) == "no"


def test_negation():
    t = "{% if not sticky %}normal{% endif %}"
    assert render_string(t, {"sticky": False}) == "normal"
    assert render_string(t, {"sticky": True}) == ""


def test_nested_conditionals():
    t = "{% if a %}{% if b %}ab{% endif %}{% endif %}"
    assert render_string(t, {"a": True, "b": True}) == "ab"
    assert render_string(t, {"a": True, "b": False}) == ""


def test_whitespace_trim_leaves_no_blank_gap_when_branch_removed():
    t = "X\n{% if demo %}\nY\n{% endif %}\nZ\n"
    assert render_string(t, {"demo": False}) == "X\nZ\n"
    assert render_string(t, {"demo": True}) == "X\nY\nZ\n"


def test_keep_trailing_newline():
    assert render_string("line\n", {}) == "line\n"


def test_basis_syntax_is_not_template_syntax():
    # single-brace reactivity, $store DSL and @decorators pass through untouched
    t = "<div>{count}</div> <span>$store.items</span> @app.page(path=\"/\")"
    assert render_string(t, {}) == t


def test_raw_block_escapes_jinja_delimiters():
    assert render_string("{% raw %}{{ literal }}{% endraw %}", {}) == "{{ literal }}"


# --- layout context + inventory -------------------------------------------

def test_layout_context_reflects_flags_and_derived_booleans():
    cfg = ShellConfig(project_name="demo", paradigm=PARADIGM_SITE, footer=False, demo=False)
    ctx = build_context(cfg)
    assert ctx["slug"] == "demo"
    assert ctx["project_title"] == "Demo"
    assert ctx["is_app"] is False
    assert ctx["is_site"] is True
    assert ctx["has_any_sidebar"] is True  # sidebar_left default True
    assert ctx["footer"] is False
    assert ctx["demo"] is False
    assert ctx["titlebar_height"] == "48px"


def test_layout_context_from_layout_renders_a_frame_snippet():
    cfg = ShellConfig(project_name="demo", sidebar_right=True)
    ctx = build_context(cfg)
    t = (
        "{{ project_title }}\n"
        "{% if titlebar %}<shell-title-bar>{% endif %}\n"
        "{% if sidebar_right %}<shell-sidebar-right>{% endif %}\n"
    )
    out = render_string(t, ctx)
    assert "Demo" in out
    assert "<shell-title-bar>" in out
    assert "<shell-sidebar-right>" in out


def test_inventory_includes_base_files_always():
    cfg = ShellConfig(project_name="demo")
    dests = [dest_path(t, cfg) for t in build_inventory(cfg)]
    assert "pyproject.toml" in dests
    assert "src/demo/__init__.py" in dests
    assert "src/demo/components/page.py" in dests
    assert "src/demo/components/app_container.py" in dests


def test_inventory_app_chrome_follows_part_flags():
    cfg = ShellConfig(project_name="demo", titlebar=True, statusbar=False,
                      activitybar=True, sidebar_left=True, sidebar_right=False)
    dests = [dest_path(t, cfg) for t in build_inventory(cfg)]
    assert "src/demo/components/titlebar.py" in dests
    assert "src/demo/components/statusbar.py" not in dests
    assert "src/demo/components/activitybar.py" in dests
    assert "src/demo/components/sidebar.py" in dests
    assert "src/demo/components/tabsbar.py" not in dests


def test_inventory_site_paradigm_excludes_workbench_parts():
    cfg = ShellConfig(project_name="demo", paradigm=PARADIGM_SITE)
    dests = [dest_path(t, cfg) for t in build_inventory(cfg)]
    assert "src/demo/components/titlebar.py" not in dests
    assert "src/demo/components/statusbar.py" not in dests
    assert "src/demo/components/app_container.py" in dests  # root still generated


def test_inventory_extras_follow_flags():
    cfg = ShellConfig(project_name="demo", example_store=False, example_plugin=True)
    dests = [dest_path(t, cfg) for t in build_inventory(cfg)]
    assert "src/demo/stores/app_state.py" not in dests
    assert "src/demo/plugins/demo.py" in dests


def test_dest_path_substitutes_slug():
    cfg = ShellConfig(project_name="My-App")
    from basis.cli.init.registry import TEMPLATE_FILES
    titlebar = next(t for t in TEMPLATE_FILES if t.dest.endswith("titlebar.py"))
    assert dest_path(titlebar, cfg) == "src/my_app/components/titlebar.py"
