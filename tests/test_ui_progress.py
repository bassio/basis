"""
Tests for ``ui-progress`` (``basis.plugins.ui.progress``).

The bar is data plus a stylesheet: the fraction travels as a custom property so the
geometry stays restatable, and the ``value``-less state is a real branch (an
indeterminate bar announces no number at all) rather than a zero-width fill.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

import basis.plugins.ui.progress.progress  # noqa: F401
from basis.plugins.ui.progress import Progress
from basis.shared.styling import reduced_motion_block

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
    # The page inlines the family's stylesheet, which names the same classes the
    # markup does; these assertions are about the rendered element.
    return _STYLE.sub("", resp.text)


class _ProgressFixture(Component):
    value = "37"
    label = "Uploading"
    variant = "primary"
    size = "md"

    def template(self):
        """
        <div class="root">
            <ui-progress value="{value}" total="100" label="{label}"
                         variant="{variant}" size="{size}"></ui-progress>
        </div>
        """


def test_ui_progress_tag():
    assert Progress.__tag__ == "ui-progress"


def test_the_fraction_travels_as_a_custom_property():
    """The fill's width stays a rule, so a theme can restate it."""
    html = _render(_ProgressFixture, "/test_progress_measured.py")

    assert "--progress-value: 37%;" in html
    assert 'aria-valuenow="37"' in html
    assert 'aria-valuemax="100"' in html


def test_a_measured_bar_renders_the_value_beside_its_label():
    html = _render(_ProgressFixture, "/test_progress_caption.py")

    assert "Uploading" in html
    assert ">37%<" in html


def test_no_value_means_indeterminate():
    """An unmeasured bar announces no number, rather than claiming 0%."""
    class Unmeasured(_ProgressFixture):
        value = ""

    html = _render(Unmeasured, "/test_progress_indeterminate.py")

    assert "ui-progress-indeterminate" in html
    assert "aria-valuenow" not in html, "an indeterminate bar has no value to announce"
    assert "--progress-value" not in html
    assert ">37%<" not in html


def test_zero_is_a_measurement():
    """``0`` is a real position on the scale, not the same as "unmeasured"."""
    class Empty(_ProgressFixture):
        value = "0"

    html = _render(Empty, "/test_progress_zero.py")

    assert 'aria-valuenow="0"' in html
    assert "ui-progress-indeterminate" not in html


def test_a_value_beyond_the_scale_is_clamped():
    class Overflowing(_ProgressFixture):
        value = "250"

    html = _render(Overflowing, "/test_progress_clamped.py")

    assert "--progress-value: 100%;" in html
    assert 'aria-valuenow="100"' in html


def test_the_variant_reaches_the_stylesheet():
    class Warning(_ProgressFixture):
        variant = "warning"

    html = _render(Warning, "/test_progress_variant.py")

    assert "ui-progress-warning" in html


def test_the_default_variant_ships_no_rule():
    """``primary`` *is* the base bar, so a rule for it would be a second definition."""
    css = Progress._get_style_string()

    assert ".ui-progress-success" in css
    assert ".ui-progress-primary" not in css


def test_the_sweep_is_a_shared_motion_preference_rule():
    """A user who asked for less movement gets a still bar that still says "working"."""
    css = Progress._get_style_string()

    assert reduced_motion_block("").split("\n")[0] in css
    reduced = css.split("(prefers-reduced-motion: reduce)", 1)[1]
    assert "animation: none" in reduced


def test_the_family_owns_no_viewport_query():
    css = Progress._get_style_string()

    assert "@media (max-width" not in css
