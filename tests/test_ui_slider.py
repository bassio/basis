"""
Tests for ``ui-slider`` (``basis.plugins.ui.slider``).

The control is the native range input, so the interesting parts are the bounds it
hands the engine, the fraction it publishes for the rail's fill, and the touch sizing.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

import basis.plugins.ui.slider.slider  # noqa: F401
from basis.plugins.ui.slider import Slider
from basis.shared.pointer import COARSE_QUERY, HOVER_QUERY

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


class _SliderFixture(Component):
    value = "30"
    low = "0"
    high = "100"
    step = "5"
    label = "Opacity"
    disabled = ""

    def template(self):
        """
        <div class="root">
            <ui-slider value="{value}" min="{low}" max="{high}" step="{step}"
                       label="{label}" disabled="{disabled}"></ui-slider>
        </div>
        """


def test_ui_slider_tag():
    assert Slider.__tag__ == "ui-slider"


def test_the_bounds_reach_the_native_input():
    """``min``/``max``/``step`` are builtin names in a template expression, so they
    travel as a dict — this is the assertion that keeps that workaround working."""
    html = _render(_SliderFixture, "/test_slider_bounds.py")

    assert 'min="0"' in html
    assert 'max="100"' in html
    assert 'step="5"' in html


def test_the_engine_gets_the_value_the_rail_shows():
    html = _render(_SliderFixture, "/test_slider_value.py")

    assert 'value="30"' in html
    assert "--slider-fill: 30%;" in html


def test_a_value_outside_the_range_is_clamped():
    class Overshooting(_SliderFixture):
        value = "180"

    class Undershooting(_SliderFixture):
        value = "-20"

    assert "--slider-fill: 100%;" in _render(Overshooting, "/test_slider_high.py")
    assert "--slider-fill: 0%;" in _render(Undershooting, "/test_slider_low.py")


def test_an_unset_value_sits_at_the_bottom():
    class Unset(_SliderFixture):
        value = ""

    html = _render(Unset, "/test_slider_unset.py")

    assert "--slider-fill: 0%;" in html
    assert 'value="0"' in html


def test_the_label_carries_the_current_value():
    html = _render(_SliderFixture, "/test_slider_label.py")

    assert "Opacity" in html
    assert re.search(r'class="ui-slider-value"[^>]*>30<', html)


def test_a_disabled_slider_says_so():
    class Disabled(_SliderFixture):
        disabled = "true"

    html = _render(Disabled, "/test_slider_disabled.py")

    assert "ui-slider-disabled" in html
    assert " disabled" in html


def test_the_rail_fill_is_a_custom_property():
    """The fraction is data, and data may not be written into markup as layout."""
    css = Slider._get_style_string()

    assert "background-size: var(--slider-fill, 0%)" in css


def test_the_thumb_grows_to_the_touch_target():
    css = Slider._get_style_string()
    coarse = css.split(COARSE_QUERY, 1)[1]

    assert "var(--touch-target, 44px)" in coarse
    assert "::-webkit-slider-thumb" in coarse, "WebKit sizes its thumb separately"
    assert "::-moz-range-thumb" in coarse, "so does Gecko"


def test_the_family_owns_no_viewport_query():
    assert "@media (max-width" not in Slider._get_style_string()


def test_hover_is_capability_guarded():
    css = Slider._get_style_string()
    unguarded = css.split(HOVER_QUERY, 1)[0]

    assert ":hover" not in unguarded
