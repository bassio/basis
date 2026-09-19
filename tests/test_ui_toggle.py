"""
Tests for ``ui-toggle``'s arrangements (``basis.plugins.ui.toggle``).

The settings row is an arrangement of the same switch — one declaration, one control,
two shapes — so ``auto`` must stay exactly the component it was: the base shape ships no
rule of its own.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

import basis.plugins.ui.toggle.toggle  # noqa: F401
from basis.plugins.ui.toggle import Toggle

_STYLE = re.compile(r"<style.*?</style>", re.DOTALL)


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes


def _render(root_component, entry_module):
    app = Basis()
    app.bootstrap()
    app.include_page(
        "/", page_cls=_synthesize_page(root_component, entry_module=entry_module)
    )
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    return _STYLE.sub("", resp.text)


class _ToggleFixture(Component):
    arrangement = "auto"
    label = ""

    def template(self):
        """
        <div class="root">
            <ui-toggle arrangement="{arrangement}" label="{label}"
                       first="off" second="on"></ui-toggle>
        </div>
        """


def test_the_arrangement_is_reflected_in_the_markup():
    class Row(_ToggleFixture):
        arrangement = "row"

    html = _render(Row, "/test_toggle_row.py")

    assert 'data-arrangement="row"' in html


def test_the_base_shape_ships_no_rule():
    """``auto`` has one definition — the component itself."""
    css = Toggle._get_style_string()

    assert '[data-arrangement="row"]' in css
    assert '[data-arrangement="auto"]' not in css


def test_the_row_uses_the_page_scale_for_its_height():
    css = Toggle._get_style_string()

    assert "min-height: var(--row-height, 2rem)" in css


def test_a_row_is_full_width():
    """The host shrink-wraps the inline switch, which a full-width row cannot live in."""
    css = Toggle._get_style_string()

    assert ':scope:has(> .switch-container[data-arrangement="row"])' in css
    assert "width: 100%" in css.split('[data-arrangement="row"] {', 1)[1].split("}", 1)[0]


def test_the_label_names_the_control_itself():
    """The control is a ``<label>``, so the text is its accessible name — not a caption
    that merely happens to sit next to it."""
    class Labelled(_ToggleFixture):
        label = "Dark mode"

    html = _render(Labelled, "/test_toggle_label.py")

    assert "Dark mode" in html
    assert re.search(r"<label class=\"switch-container\"[^>]*>", html)


def test_an_unlabelled_switch_renders_no_label_element():
    html = _render(_ToggleFixture, "/test_toggle_unlabelled.py")

    assert "toggle-label" not in html
