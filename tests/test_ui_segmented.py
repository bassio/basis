"""
Tests for ``ui-segmented`` (``basis.plugins.ui.segmented``).

One declaration renders every segment, the pressed one is derived from ``value``, and
the clicked segment reports its own id — so the handler needs no per-item wiring.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page
from basis.shared.reactive import state
from basis.shared.styling import COARSE_QUERY, compact_media

import basis.plugins.ui.segmented.segmented  # noqa: F401
from basis.plugins.ui.segmented import Segmented

_STYLE = re.compile(r"<style.*?</style>", re.DOTALL)

ITEMS = [
    {"id": "list", "label": "List"},
    {"id": "grid", "label": "Grid"},
    {"id": "board", "label": "Board", "disabled": True},
]


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


class _SegmentedFixture(Component):
    items: list = state(default_factory=lambda: [dict(item) for item in ITEMS])
    value = "grid"
    label = "View"
    disabled = ""

    def template(self):
        """
        <div class="root">
            <ui-segmented items="{items}" value="{value}" label="{label}"
                          disabled="{disabled}"></ui-segmented>
        </div>
        """


class _FakeEvent:
    """The only part of a click the handler reads."""

    def __init__(self, attrs):
        self.currentTarget = _FakeTarget(attrs)


class _FakeTarget:
    def __init__(self, attrs):
        self._attrs = attrs

    def getAttribute(self, name):
        return self._attrs.get(name)


def _button(html, item_id):
    match = re.search(rf'<button[^>]*data-segment="{item_id}"[^>]*>', html)
    assert match, f"no button rendered for {item_id}"
    return match.group(0)


def test_ui_segmented_tag():
    assert Segmented.__tag__ == "ui-segmented"


def test_one_button_per_item():
    html = _render(_SegmentedFixture, "/test_segmented_items.py")

    for item in ("list", "grid", "board"):
        assert _button(html, item)


def test_the_pressed_state_is_derived_from_the_value():
    html = _render(_SegmentedFixture, "/test_segmented_pressed.py")

    assert 'aria-pressed="true"' in _button(html, "grid")
    assert 'aria-pressed="false"' in _button(html, "list")


def test_a_disabled_item_says_so():
    html = _render(_SegmentedFixture, "/test_segmented_item_disabled.py")

    assert 'aria-disabled="true"' in _button(html, "board")
    assert 'aria-disabled="false"' in _button(html, "list")


def test_a_disabled_control_presses_nothing():
    """A whole control that is off must not render a selection the user cannot move."""
    class Disabled(_SegmentedFixture):
        disabled = "true"

    html = _render(Disabled, "/test_segmented_disabled.py")

    assert 'aria-pressed="true"' not in html
    assert html.count('aria-disabled="true"') == 3


def test_clicking_an_item_selects_it():
    control = Segmented()
    control.items = ITEMS
    control.value = "list"

    control.on_segment_click(_FakeEvent({"data-segment": "grid"}))

    assert control.value == "grid"


def test_clicking_a_disabled_item_is_ignored():
    control = Segmented()
    control.items = ITEMS
    control.value = "list"

    control.on_segment_click(
        _FakeEvent({"data-segment": "board", "aria-disabled": "true"})
    )

    assert control.value == "list"


def test_clicking_the_pressed_item_is_not_a_change():
    control = Segmented()
    control.value = "grid"

    control.on_segment_click(_FakeEvent({"data-segment": "grid"}))

    assert control.value == "grid"


def test_plain_strings_are_items_too():
    class Names(_SegmentedFixture):
        items: list = state(default_factory=lambda: ["Day", "Week", "Month"])
        value = "Week"

    html = _render(Names, "/test_segmented_strings.py")

    assert _button(html, "Week")
    assert 'aria-pressed="true"' in _button(html, "Week")


def test_the_group_is_named_by_its_label():
    html = _render(_SegmentedFixture, "/test_segmented_group.py")

    assert 'role="group"' in html
    assert 'aria-label="View"' in html


def test_the_compact_arrangement_fills_the_width_and_snaps():
    css = Segmented._get_style_string()
    compact = css.split(compact_media(), 1)[1]

    assert "width: 100%" in compact
    assert "scroll-snap-type: x mandatory" in compact
    assert "scroll-snap-align: start" in compact, "the scrolling segments land on an edge"


def test_the_segments_grow_to_the_touch_target():
    css = Segmented._get_style_string()
    coarse = css.split(COARSE_QUERY, 1)[1]

    assert "var(--touch-target, 44px)" in coarse


def test_the_compact_block_owns_no_literal_viewport_or_height():
    """The phone height is the page's scale, so the compact block only restates layout."""
    css = Segmented._get_style_string()
    compact = css.split(compact_media(), 1)[1]

    assert "px;" not in compact
