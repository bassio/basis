"""
Tests for the ``ui-icon`` component (``basis.plugins.ui.icon``).

A general-purpose inline icon: renders a glyph with a tooltip, an optional
active state (Python bool) and an optional interactive (pointer-cursor) state.
"""
import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.page import _synthesize_page
from basis.shared.component import Component

# Registers the <ui-icon> custom element.
import basis.plugins.ui.icon.icon  # noqa: F401
from basis.plugins.ui.icon import Icon


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
    app.include_page("/", page_cls=_synthesize_page(root_component, entry_module=entry_module))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    return resp.text


def test_ui_icon_tag():
    assert Icon.__tag__ == "ui-icon"


def test_ui_icon_renders_glyph_title_and_view():
    class Root(Component):
        """
        <div class="root">
            <ui-icon content="📁" title="Explorer" view="teams"></ui-icon>
        </div>
        """

    html = _render(Root, "/test_ui_icon.py")
    assert "ui-icon" in html
    assert 'title="Explorer"' in html
    assert 'data-view="teams"' in html
    assert "📁" in html


def test_ui_icon_active_class_from_python_bool():
    class Root(Component):
        """
        <div class="root">
            <ui-icon content="📁" active="{flag}"></ui-icon>
        </div>
        """
        flag = True

    html = _render(Root, "/test_ui_icon_active.py")
    assert 'class="ui-icon active"' in html


def test_ui_icon_inactive_has_no_active_class():
    class Root(Component):
        """
        <div class="root">
            <ui-icon content="🔍" active="{flag}"></ui-icon>
        </div>
        """
        flag = False

    html = _render(Root, "/test_ui_icon_inactive.py")
    assert "ui-icon" in html
    assert 'class="ui-icon active"' not in html


def test_ui_icon_interactive_renders_data_attr():
    class Root(Component):
        """
        <div class="root">
            <ui-icon content="⚙" interactive="{flag}"></ui-icon>
        </div>
        """
        flag = True

    html = _render(Root, "/test_ui_icon_interactive.py")
    assert 'data-interactive="True"' in html


def test_ui_icon_size_and_color_style():
    class Root(Component):
        """
        <div class="root">
            <ui-icon content="📁" size="20px" color="red"></ui-icon>
        </div>
        """

    html = _render(Root, "/test_ui_icon_style.py")
    assert "font-size: 20px" in html
    assert "color: red" in html
