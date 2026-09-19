"""
Tests for ``ui-list`` / ``ui-list-item`` (``basis.plugins.ui.list``).

The container is a column; the row is one box with optional surround, and the two are
siblings in the DOM — which is also the seam a windowed renderer needs, since rows are
ordinary children that can be mounted and unmounted.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.breakpoints import compact_media
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

import basis.plugins.ui.list.list  # noqa: F401
from basis.plugins.ui.list import List, ListItem

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


class _ListFixture(Component):
    selected = ""

    def template(self):
        """
        <ui-list>
            <ui-list-item arrangement="header">Today</ui-list-item>
            <ui-list-item label="Groceries" href="/notes/1" selected="{selected}">
                <span slot="leading">🗒</span>
                <span slot="trailing">2m</span>
            </ui-list-item>
            <ui-list-item label="Second note"></ui-list-item>
        </ui-list>
        """


def test_the_two_tags():
    assert List.__tag__ == "ui-list"
    assert ListItem.__tag__ == "ui-list-item"


def test_the_row_keeps_its_content_inside_one_box():
    """One box per row, so the list is a column of rows and nothing else."""
    html = _render(_ListFixture, "/test_list_rows.py")

    assert html.count('class="ui-list-row"') == 3
    assert "Groceries" in html


def test_a_titled_row_renders_its_own_link():
    """The looped row gets its data as attributes, so the row renders the anchor."""
    html = _render(_ListFixture, "/test_list_link.py")

    assert re.search(r'<a class="ui-list-link"[^>]*href="/notes/1"[^>]*>Groceries</a>', html)


def test_a_row_without_a_link_renders_plain_text():
    html = _render(_ListFixture, "/test_list_plain.py")

    assert re.search(r'<span class="ui-list-text"[^>]*>Second note</span>', html)
    assert "ui-list-link" not in html.split("Second note")[0].split("Groceries")[-1]


def test_leading_and_trailing_are_slots():
    html = _render(_ListFixture, "/test_list_slots.py")

    assert 'slot="leading"' in html
    assert 'slot="trailing"' in html
    assert "🗒" in html and "2m" in html


def test_the_selected_row_says_so_in_markup():
    class Selected(_ListFixture):
        selected = "true"

    html = _render(Selected, "/test_list_selected.py")

    assert 'data-selected="true"' in html


def test_a_selection_bound_from_a_store_still_marks_the_row():
    """A bound flag arrives as ``True``/``"True"``, which is not the markup's spelling."""
    class Bound(_ListFixture):
        selected = "True"

    assert 'data-selected="true"' in _render(Bound, "/test_list_bound.py")


def test_the_header_is_an_arrangement_of_the_same_row():
    html = _render(_ListFixture, "/test_list_header.py")
    css = ListItem._get_style_string()

    assert 'data-arrangement="header"' in html
    assert '[data-arrangement="header"]' in css
    assert "position: sticky" in css


def test_a_header_can_be_offset_below_its_frame_chrome():
    """A frame with sticky chrome of its own would otherwise cover the header."""
    assert "var(--list-sticky-top, 0px)" in ListItem._get_style_string()


def test_the_hairline_is_the_lists_and_skips_the_first_row():
    """A row cannot know it is first: the list does, and a loop may wrap each row."""
    css = List._get_style_string()

    assert ".ui-list .ui-list-row" in css
    assert ".ui-list > :first-child .ui-list-row:first-child" in css
    assert "border-top: 1px solid" in css
    assert "border-top: 0" in css


def test_a_row_standing_alone_draws_no_hairline():
    assert "border-top" not in ListItem._get_style_string()


def test_rows_take_the_page_scale():
    """Phone-sized without owning a viewport query: the row height is the page's."""
    css = ListItem._get_style_string()

    assert "min-height: var(--row-height, 2rem)" in css


def test_an_unused_slot_cannot_shift_the_row():
    """A placeholder left in the DOM must not become a flex item with a gap of its own."""
    css = ListItem._get_style_string()

    assert ".ui-list-row > slot" in css
    assert "display: contents" in css.split(".ui-list-row > slot", 1)[1].split("}", 1)[0]


def test_a_row_link_fills_the_row():
    """The whole row is the target, not the words in it."""
    css = ListItem._get_style_string()

    assert ".ui-list-content > a::after" in css, "the row's own link"
    assert ".ui-list-row > a::after" in css, "a link the caller slots in"
    assert "position: absolute" in css
    assert "inset: 0" in css


def test_the_row_pads_itself_to_the_page_gutter_at_compact():
    """So a full-bleed list still lines its text up with the rest of the page."""
    css = ListItem._get_style_string()
    compact = css.split(compact_media(), 1)[1]

    assert "padding-inline: var(--page-gutter, 1.5rem)" in compact


def test_the_list_stays_a_column_and_never_overflows_its_box():
    css = List._get_style_string()

    assert "flex-direction: column" in css
    assert "min-height: 0" in css, "a list in a flex pane has to be able to scroll"
