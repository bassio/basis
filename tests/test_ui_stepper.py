"""
Tests for ``ui-stepper`` (``basis.plugins.ui.stepper``).

The control clamps at its bounds and announces the new value; the button that hit a
bound says so in place, rather than vanishing and moving the other target.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

import basis.plugins.ui.stepper.stepper  # noqa: F401
from basis.plugins.ui.stepper import Stepper
from basis.shared.pointer import COARSE_QUERY

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


class _StepperFixture(Component):
    value = "3"
    low = "1"
    high = "5"
    step = "1"
    label = "Rows"
    disabled = ""

    def template(self):
        """
        <div class="root">
            <ui-stepper value="{value}" min="{low}" max="{high}" step="{step}"
                        label="{label}" disabled="{disabled}"></ui-stepper>
        </div>
        """


def _component(**overrides):
    """A bare instance, for the arithmetic that needs no DOM."""
    instance = Stepper()
    for name, value in overrides.items():
        setattr(instance, name, value)
    return instance


def test_ui_stepper_tag():
    assert Stepper.__tag__ == "ui-stepper"


def test_the_value_and_its_label_render():
    html = _render(_StepperFixture, "/test_stepper_value.py")

    assert "Rows" in html
    assert re.search(r'class="ui-stepper-value"[^>]*>3<', html)


def test_the_buttons_are_named_as_a_group():
    """Two unlabelled "Decrease" buttons in one page are ambiguous by name alone."""
    html = _render(_StepperFixture, "/test_stepper_group.py")

    assert 'role="group"' in html
    assert 'aria-label="Rows"' in html


def test_each_button_says_whether_it_can_move():
    class AtBottom(_StepperFixture):
        value = "1"

    class AtTop(_StepperFixture):
        value = "5"

    bottom = _render(AtBottom, "/test_stepper_bottom.py")
    top = _render(AtTop, "/test_stepper_top.py")

    assert bottom.count('aria-disabled="true"') == 1
    assert top.count('aria-disabled="true"') == 1
    assert 'aria-valuenow' not in bottom, "a plain stepper claims no spinbutton role"


def test_an_unbounded_stepper_never_disables_a_button():
    class Unbounded(_StepperFixture):
        low = ""
        high = ""

    assert 'aria-disabled="true"' not in _render(Unbounded, "/test_stepper_open.py")


def test_stepping_clamps_at_the_bounds():
    at_top = _component(value="5", min="1", max="5")

    at_top.nudge(1)

    assert at_top.value == "5", "a press past the bound leaves the value alone"


def test_stepping_moves_by_the_increment():
    instance = _component(value="3", min="0", max="10", step="2")

    instance.nudge(2)

    assert instance.value == "5"


def test_fractional_steps_do_not_leak_float_artefacts():
    """A tenth-sized step quickly produces 0.30000000000000004 if left as a float."""
    instance = _component(value="0.1", min="0", max="1", step="0.1")

    instance.nudge(0.1)

    assert instance.value == "0.2"


def test_the_value_is_clamped_before_the_first_press():
    instance = _component(value="99", min="0", max="5")

    assert instance.stepper_view["value"] == "5"


def test_a_disabled_stepper_disables_its_buttons():
    class Disabled(_StepperFixture):
        disabled = "true"

    html = _render(Disabled, "/test_stepper_disabled.py")

    assert html.count(" disabled") >= 2


def test_the_buttons_grow_to_the_touch_target():
    css = Stepper._get_style_string()
    coarse = css.split(COARSE_QUERY, 1)[1]

    assert "var(--touch-target, 44px)" in coarse


def test_the_family_owns_no_viewport_query():
    """The page scale already makes this row finger-sized at compact."""
    assert "@media (max-width" not in Stepper._get_style_string()
