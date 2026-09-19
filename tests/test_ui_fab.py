"""
Tests for ``ui-fab`` (``basis.plugins.ui.fab``).

The interesting claim is where the button lands: a gutter above the bottom edge, clear
of the home indicator, and clear of anything the page has already pinned there.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page
from basis.shared.pointer import COARSE_QUERY

import basis.plugins.ui.fab.fab  # noqa: F401
from basis.plugins.ui.fab import Fab

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


class _FabFixture(Component):
    icon = "＋"
    label = "New note"
    extended = ""
    disabled = ""

    def template(self):
        """
        <div class="root">
            <ui-fab icon="{icon}" label="{label}" extended="{extended}"
                    disabled="{disabled}"></ui-fab>
        </div>
        """


def test_ui_fab_tag():
    assert Fab.__tag__ == "ui-fab"


def test_the_label_names_the_button_even_when_only_the_glyph_is_visible():
    html = _render(_FabFixture, "/test_fab_circle.py")

    assert 'aria-label="New note"' in html
    assert "＋" in html
    assert "ui-fab-extended" not in html


def test_an_extended_fab_shows_its_label():
    class Extended(_FabFixture):
        extended = "true"

    html = _render(Extended, "/test_fab_extended.py")

    assert "ui-fab-extended" in html
    assert "New note" in html


def test_a_disabled_fab_is_disabled():
    class Disabled(_FabFixture):
        disabled = "true"

    html = _render(Disabled, "/test_fab_disabled.py")

    assert " disabled" in html


def test_the_fab_clears_the_bottom_edge():
    css = Fab._get_style_string()

    assert "position: fixed" in css
    assert "var(--page-gutter, 1.5rem)" in css
    assert "inset-inline-end" in css, "the inline end keeps the control right in both directions"


def test_the_fab_clears_whatever_the_page_pinned_to_the_bottom():
    """A docked nav publishes its own height, so the two never overlap unawares."""
    css = Fab._get_style_string()

    assert "var(--shell-bottom-inset, var(--safe-area-bottom, 0px))" in css


def test_the_finger_floor_survives_a_dense_theme():
    css = Fab._get_style_string()
    coarse = css.split(COARSE_QUERY, 1)[1]

    assert "var(--touch-target, 44px)" in coarse


def test_the_family_owns_no_viewport_query():
    assert "@media (max-width" not in Fab._get_style_string()
