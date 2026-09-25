"""A component in a loop body — the two shapes, and how per-item data reaches each.

The framework renders a loop two ways, and the difference decides where an item's data
can be read:

- the loop element is a **plain element** → the body's bindings are the owner's, scoped
  per item, so content inside a component *in* that body resolves against the item;
- the loop element **is a component** → the component owns its subtree, so per-item data
  reaches it as attributes (``label="{it['title']}"``), never through its content.

Both shapes are legitimate; what is not legitimate is a body binding crashing the loop
because a binding beside it (a child component) has no reactive ``fields`` of its own.
"""

import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.page import _synthesize_page
from basis.shared.reactive import state

import basis.plugins.ui.card.card  # noqa: F401
from basis.plugins.ui.card.card import Card


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes


class _Row(Component):
    __tag__ = "loop-probe-row"

    label = ""

    def style(self):
        """
        loop-probe-row {
            display: block;
        }
        """

    def template(self):
        """
        <div class="probe-row">{label}<slot></slot></div>
        """


def _render(root_component, entry_module):
    app = Basis()
    app.bootstrap()
    app.include_page(
        "/", page_cls=_synthesize_page(root_component, entry_module=entry_module)
    )
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    return re.sub(r"<style.*?</style>", "", resp.text, flags=re.DOTALL)


def test_a_component_inside_a_loop_body_reads_the_item():
    """The plain-element body's bindings cover the component's content too."""
    class Owner(Component):
        notes: list = state(default_factory=lambda: [
            {"id": "a", "title": "Alpha"}, {"id": "b", "title": "Beta"}
        ])

        def template(self):
            """
            <div>
                <div for="note" in="{notes}" key="id"><ui-card>{note['title']}</ui-card></div>
            </div>
            """

    html = _render(Owner, "/test_loop_component_body.py")

    assert "Alpha" in html and "Beta" in html
    assert "{note['title']}" not in html


def test_an_owners_field_bound_beside_the_item_stays_reactive():
    """A component in a plain body takes BOTH: the item's fields and the owner's.

    The item-only path (a component as the loop element) refreshes its attributes only
    when the item changes, so a selection bound to an owner field has to go through the
    body — which is what makes the highlighted row follow the store.
    """
    class Owner(Component):
        notes: list = state(default_factory=lambda: [{"id": 1}, {"id": 2}])
        active = 2

        def template(self):
            """
            <div>
                <div for="note" in="{notes}" key="id">
                    <ui-card label="{note['id']}"
                             selected="{note['id'] == active}"></ui-card>
                </div>
            </div>
            """

    html = _render(Owner, "/test_loop_component_owner_field.py")

    cards = re.findall(r"<ui-card[^>]*>", html)
    assert len(cards) == 2, cards
    assert 'selected="False"' in cards[0]
    assert 'selected="True"' in cards[1]


def test_a_component_as_the_loop_element_gets_its_data_as_attributes():
    """The component owns its subtree, so an item reaches it through its props."""
    class Owner(Component):
        notes: list = state(default_factory=lambda: [
            {"id": "a", "title": "Alpha"}, {"id": "b", "title": "Beta"}
        ])

        def template(self):
            """
            <div>
                <loop-probe-row for="note" in="{notes}" key="id"
                                label="{note['title']}"></loop-probe-row>
            </div>
            """

    html = _render(Owner, "/test_loop_component_element.py")

    rows = re.findall(r'class="probe-row"[^>]*>([^<]*)', html)
    assert rows == ["Alpha", "Beta"], rows


def test_resolved_loop_prop_with_braces_remains_literal():
    class Owner(Component):
        notes: list = state(default_factory=lambda: [
            {"id": "a", "title": "{literal braces}"}
        ])

        def template(self):
            """
            <div>
                <loop-probe-row for="note" in="{notes}" key="id"
                                label="{note['title']}"></loop-probe-row>
            </div>
            """

    html = _render(Owner, "/test_loop_component_literal_braces.py")

    assert "{literal braces}" in html


def test_a_loop_body_beside_a_child_component_still_builds():
    """The body's other bindings must not depend on a component binding's fields."""
    class Owner(Component):
        notes: list = state(default_factory=lambda: [{"id": "a", "title": "Alpha"}])
        heading = "Notes"

        def template(self):
            """
            <div>
                <div for="note" in="{notes}" key="id">
                    <span class="probe-heading">{heading}</span>
                    <ui-card>{note['title']}</ui-card>
                </div>
            </div>
            """

    html = _render(Owner, "/test_loop_component_mixed.py")

    assert "Notes" in html
    assert "Alpha" in html
