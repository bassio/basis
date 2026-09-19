"""
Tests for ``ui-calendar``'s compact pass (``basis.plugins.ui.calendar``).

The month grid is seven columns of square targets, which is exactly the arithmetic a
phone is tightest on: at compact the frame stops capping its width and hands its own
padding and the grid gaps to the targets.
"""
import re

import pytest
from fastapi.testclient import TestClient

from _catalogue import guarded_block_bodies
from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page
from basis.shared.styling import COARSE_QUERY, compact_media

import basis.plugins.ui.calendar.calendar  # noqa: F401
from basis.plugins.ui.calendar import Calendar

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


class _CalendarFixture(Component):
    def template(self):
        """
        <div class="root"><ui-calendar update="picked"></ui-calendar></div>
        """


def _css():
    """Every stylesheet the calendar injects: the base plus the compact block."""
    parts = [Calendar._get_style_string() or ""]
    parts.extend(css for _name, css in Calendar._get_extra_styles())
    return "\n".join(parts)


def test_ui_calendar_tag():
    assert Calendar.__tag__ == "ui-calendar"


def test_the_month_grid_renders():
    html = _render(_CalendarFixture, "/test_calendar_render.py")

    assert "calendar-grid" in html
    assert html.count("day-cell") > 7


def test_the_desktop_frame_caps_its_width():
    base = _css().split(compact_media(), 1)[0]

    assert "max-width: 380px" in base


def test_a_phone_gets_the_whole_width():
    """A fixed 380px frame inside a 360px phone is a calendar that will not fit."""
    compact = _css().split(compact_media(), 1)[1]

    assert "max-width: none" in compact


def test_the_compact_pass_tightens_the_frame_and_the_gaps():
    compact = _css().split(compact_media(), 1)[1]

    assert "padding: 8px" in compact
    assert "gap: 2px" in compact


def test_the_day_targets_stay_finger_sized():
    """Seven columns of a phone's width is where the touch target is hardest to keep."""
    day_cell = guarded_block_bodies(_css(), (COARSE_QUERY,)).split(".day-cell", 1)[1]

    assert "min-height: var(--touch-target, 44px)" in day_cell.split("}", 1)[0]


def test_the_family_owns_no_hand_written_viewport_query():
    for query in re.findall(r"@media([^{]*)\{", _css()):
        assert query.strip() in (compact_media().removeprefix("@media "), COARSE_QUERY, "(hover: hover)")
