"""
Tests for ``ui-skeleton`` (``basis.plugins.ui.skeleton``).

A placeholder is only honest when it is the size of the thing it stands in for, so the
geometry is the props and the box arrives in markup as custom properties (never as
literal layout). The shimmer stops for a user who asked for less motion.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

import basis.plugins.ui.skeleton.skeleton  # noqa: F401
from basis.plugins.ui.skeleton import Skeleton
from basis.shared.pointer import reduced_motion_block

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


class _SkeletonFixture(Component):
    variant = "text"
    lines = 1
    width = ""
    height = ""

    def template(self):
        """
        <div class="root">
            <ui-skeleton variant="{variant}" lines="{lines}"
                         width="{width}" height="{height}"></ui-skeleton>
        </div>
        """


def test_ui_skeleton_tag():
    assert Skeleton.__tag__ == "ui-skeleton"


def test_one_bar_per_line():
    class Paragraph(_SkeletonFixture):
        lines = 3

    html = _render(Paragraph, "/test_skeleton_lines.py")

    assert html.count("ui-skeleton-bar\"") + html.count("ui-skeleton-bar ") >= 3


def test_only_a_paragraph_shortens_its_last_line():
    """A lone bar that stops short looks like a mistake, not a paragraph."""
    class OneLine(_SkeletonFixture):
        lines = 1

    class TwoLines(_SkeletonFixture):
        lines = 2

    assert "ui-skeleton-bar-last" not in _render(OneLine, "/test_skeleton_one.py")
    assert "ui-skeleton-bar-last" in _render(TwoLines, "/test_skeleton_two.py")


def test_the_box_arrives_as_custom_properties():
    """Geometry written into markup cannot be reached by a rule."""
    class Sized(_SkeletonFixture):
        width = "12rem"
        height = "1.25rem"

    html = _render(Sized, "/test_skeleton_sized.py")

    assert "--skeleton-width: 12rem;" in html
    assert "--skeleton-height: 1.25rem;" in html


def test_an_unsized_placeholder_declares_nothing():
    html = _render(_SkeletonFixture, "/test_skeleton_unsized.py")

    assert "--skeleton-width" not in html
    assert "--skeleton-height" not in html


def test_the_variant_reaches_the_stylesheet():
    class Avatar(_SkeletonFixture):
        variant = "circle"

    assert "ui-skeleton-circle" in _render(Avatar, "/test_skeleton_circle.py")


def test_the_shimmer_stops_for_a_reduced_motion_preference():
    css = Skeleton._get_style_string()

    assert reduced_motion_block("").split("\n")[0] in css
    reduced = css.split("(prefers-reduced-motion: reduce)", 1)[1]
    assert "animation: none" in reduced
    assert "background-image: none" in reduced


def test_the_family_owns_no_viewport_query():
    assert "@media (max-width" not in Skeleton._get_style_string()
