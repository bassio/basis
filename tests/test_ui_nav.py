"""
Tests for the ``ui-nav`` component (``basis.plugins.ui.nav``).

One declaration, rearranged by CSS: ``auto`` is an inline row that docks to the bottom
edge at compact, ``rail``/``drawer`` are columns, and the highlighted item is *derived*
from the router (page-set during SSR) rather than declared.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.styling import compact_media
from basis.shared.component import Component
from basis.shared.page import _synthesize_page
from basis.shared.store import Store

# Registers the <ui-nav> custom element (and, with it, the $router store's blueprint).
import basis.shared.router  # noqa: F401
import basis.plugins.ui.nav.nav  # noqa: F401
from basis.plugins.ui.nav import Nav
from basis.shared.router import RouterStore

LINKS = [
    {"id": "home", "label": "Home", "href": "/"},
    {"id": "notes", "label": "Notes", "href": "/notes", "icon": "🗒", "badge": "2"},
]


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    saved_stores = dict(Store._registry)
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes
    Store._registry.clear()
    Store._registry.update(saved_stores)


def _active_anchors(html):
    """Every rendered anchor whose class marks it as the active item.

    Matched as whole tags rather than by slicing after ``href``: the class attribute is
    emitted *before* the href, and the stylesheet also contains the class name.
    """
    return [
        tag
        for tag in re.findall(r"<a\b[^>]*>", html)
        if "ui-nav-item-active" in tag
    ]


def _render(root_component, entry_module, paths=("/",), target="/"):
    app = Basis()
    app.bootstrap()
    # Two framework facts this test has to respect: a page hydrates only the stores it
    # can find in the (shared, mutable) blueprint registry, and it stamps
    # ``current_path`` from the request only for a store it *creates*. So declare the
    # blueprint, then drop any live instance, and this render gets a fresh one.
    RouterStore("router")
    Store._registry.pop("router", None)
    for path in paths:
        app.include_page(
            path, page_cls=_synthesize_page(root_component, entry_module=entry_module)
        )
    client = TestClient(app)
    resp = client.get(target)
    assert resp.status_code == 200
    return resp.text


class _NavFixture(Component):
    """A page body that renders one ``ui-nav`` over :data:`LINKS`."""

    links = LINKS
    nav_arrangement = "auto"
    pinned = ""

    def template(self):
        """
        <div class="root">
            <ui-nav items="{links}" arrangement="{nav_arrangement}" active="{pinned}"></ui-nav>
        </div>
        """


def test_ui_nav_tag():
    assert Nav.__tag__ == "ui-nav"


def test_items_render_as_plain_links():
    """Plain anchors: the nav is crawlable and needs no client to work."""
    html = _render(_NavFixture, "/test_nav_links.py")

    assert 'href="/"' in html and 'href="/notes"' in html
    assert "Home" in html and "Notes" in html
    assert "🗒" in html, "the item's icon is rendered"
    assert ">2<" in html, "the item's badge is rendered"


def test_active_item_is_derived_from_the_router():
    html = _render(_NavFixture, "/test_nav_active.py", paths=("/", "/notes"), target="/notes")

    # The server knows the request path, so SSR highlights the right item and the
    # client has nothing to correct.
    active = _active_anchors(html)
    assert len(active) == 1, active
    assert 'href="/notes"' in active[0], active
    assert 'aria-current="page"' in active[0], active


def test_the_root_item_only_matches_the_root():
    """``/`` is a prefix of everything, so it must not stay lit on every page."""
    html = _render(_NavFixture, "/test_nav_root.py", paths=("/", "/notes"), target="/notes")

    assert 'href="/"' not in _active_anchors(html)


def test_an_explicit_active_id_overrides_the_router():
    class Pinned(_NavFixture):
        pinned = "home"

    html = _render(Pinned, "/test_nav_pinned.py", paths=("/", "/notes"), target="/notes")

    active = _active_anchors(html)
    assert len(active) == 1, active
    assert 'href="/"' in active[0], active


def test_arrangement_is_reflected_in_the_markup():
    """One element, one DOM: the arrangement is data the stylesheet reads."""
    class Rail(_NavFixture):
        nav_arrangement = "rail"

    html = _render(Rail, "/test_nav_rail.py")
    assert 'data-arrangement="rail"' in html


def test_auto_docks_to_the_bottom_edge_at_compact():
    css = Nav._get_style_string()

    assert compact_media() in css
    compact = css.split(compact_media(), 1)[1]
    assert "position: fixed" in compact
    assert "inset: auto 0 0 0" in compact
    assert "var(--safe-area-bottom" in compact, "the home indicator stays clear"
    assert '[data-arrangement="auto"]' in compact, "only the auto arrangement docks"


def test_item_height_comes_from_the_page_scale():
    """Phone-sized by scope, so the nav owns no sizing media query of its own."""
    css = Nav._get_style_string()

    assert "min-height: var(--control-height, 2rem)" in css
    assert "min-height: var(--row-height, 2rem)" in css, "drawer rows use the row scale"


def test_only_the_auto_arrangement_docks_at_compact():
    """``inline``/``rail``/``drawer`` must not be pinned to the bottom edge by the breakpoint."""
    compact = Nav._get_style_string().split(compact_media(), 1)[1]

    assert "\n.ui-nav {" not in compact, "the docked body leaked onto every arrangement"
    assert '.ui-nav[data-arrangement="auto"] {' in compact


def test_the_bottom_arrangement_docks_at_every_viewport():
    base = Nav._get_style_string().split(compact_media(), 1)[0]
    bottom = base.split('.ui-nav[data-arrangement="bottom"] {', 1)[1]

    assert "position: fixed" in bottom


def test_the_reservation_is_published_at_the_root_while_a_nav_is_docked():
    """A property inherits downwards, so the nav publishes the space it takes at the root.

    That rule targets ``html`` — outside the nav's own subtree — so it lives in the
    additive block and stays unscoped, because a scoped rule cannot match the page root.
    """
    inset = dict(Nav._get_extra_styles())["root_inset"]
    base, compact = inset.split(compact_media(), 1)

    assert 'html:has(.ui-nav[data-arrangement="bottom"])' in base
    assert 'html:has(.ui-nav[data-arrangement="auto"])' in compact
    assert "--shell-bottom-inset: calc(" in base and "--shell-bottom-inset: calc(" in compact

    assert not inset.lstrip().startswith("@scope"), "a scoped rule cannot reach html"
    assert "@scope (ui-nav)" in Nav._get_style_string(), "the rest of the nav is scoped"
