"""
Tests for ``ui-schedule``'s compact pass (``basis.plugins.ui.schedule``).

A time grid spends a fixed strip on its hour labels, and that strip is the first thing a
phone cannot afford. It is now one declared value the compact block restates, instead of
the same number written into four rules.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.styling import compact_media
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

import basis.plugins.ui.schedule.schedule  # noqa: F401
from basis.plugins.ui.schedule import Schedule

_STYLE = re.compile(r"<style.*?</style>", re.DOTALL)

ENTRIES = [
    {"title": "Standup", "start": "09:30", "duration": 30, "all_day": False},
    {"title": "Offsite", "start": "00:00", "duration": 0, "all_day": True},
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


class _ScheduleFixture(Component):
    entries = ENTRIES

    def template(self):
        """
        <div class="root">
            <ui-schedule entries="{entries}" time_attr="start"
                         duration_attr="duration" all_day_attr="all_day"></ui-schedule>
        </div>
        """


def _css():
    """Every stylesheet the schedule injects: the base plus the compact block."""
    parts = [Schedule._get_style_string() or ""]
    parts.extend(css for _name, css in Schedule._get_extra_styles())
    return "\n".join(parts)


def test_ui_schedule_tag():
    assert Schedule.__tag__ == "ui-schedule"


def test_the_grid_renders_its_times_and_entries():
    html = _render(_ScheduleFixture, "/test_schedule_render.py")

    assert "schedule-tick-label" in html
    assert "Standup" in html
    assert "Offsite" in html


def test_the_hour_gutter_is_declared_once():
    """One value, so the tick labels, the header rows and the now-line cannot drift."""
    css = _css()
    base = css.split(compact_media(), 1)[0]

    assert base.count("--schedule-gutter:") == 1
    for rule in (".schedule-tick-label", ".schedule-now-line"):
        body = base.split(rule, 1)[1].split("}", 1)[0]
        assert "var(--schedule-gutter)" in body, rule


def test_the_gutter_rule_owners_read_the_declared_value():
    base = _css().split(compact_media(), 1)[0]

    assert "left: var(--schedule-gutter);" in base
    assert "padding: 8px 20px 8px calc(var(--schedule-gutter) + 20px);" in base
    assert "padding: 10px 20px 10px calc(var(--schedule-gutter) + 20px);" in base


def test_a_phone_narrows_the_gutter():
    compact = _css().split(compact_media(), 1)[1]

    assert "--schedule-gutter: 44px" in compact


def test_no_hand_written_width_answers_the_compact_question():
    compact = _css().split(compact_media(), 1)[1]

    assert "54px" not in compact and "74px" not in compact
