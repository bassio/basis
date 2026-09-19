"""
Tests for the ``ui-modal`` arrangements (``basis.plugins.ui.modal``).

A modal is a panel plus a decision about *where* it sits. ``auto`` — the default — is a
centred dialog on a desktop and a bottom sheet on a phone, because the bottom edge is the
part of the screen a thumb reaches. ``sheet`` and ``fullscreen`` ask for their shape at
every viewport, and ``dialog`` asks to stay centred.

The arrangement rules ship as an additive style block (``@extra_style``), i.e. *after* the
main stylesheet — which is what lets the sheet's slide-up ``transform`` beat the
scale-in/out rules in a tie on specificity.
"""
import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.styling import compact_media
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

# Registers the <ui-modal> custom element.
import basis.plugins.ui.modal.modal  # noqa: F401
from basis.plugins.ui.modal.modal import Modal


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
    return resp.text


def _arrangement_css() -> str:
    """The additive block carrying every arrangement rule."""
    blocks = dict(Modal._get_extra_styles())
    assert "arrangements" in blocks, list(blocks)
    return blocks["arrangements"]


def _sheet_half(css: str, arrangement: str) -> str:
    """The rules for *arrangement*, up to the next rule."""
    marker = f'.ui-modal-backdrop[data-arrangement="{arrangement}"]'
    assert marker in css, marker
    return css.split(marker, 1)[1]


def test_ui_modal_tag_and_defaults():
    assert Modal.__tag__ == "ui-modal"
    assert Modal.arrangement == "auto", "centred on a desktop, a sheet on a phone"


def test_the_arrangement_reaches_the_markup():
    class Root(Component):
        """
        <div class="root"><ui-modal arrangement="sheet" title="Hi"></ui-modal></div>
        """

    html = _render(Root, "/test_modal_sheet.py")
    assert 'data-arrangement="sheet"' in html


def test_a_sheet_is_anchored_to_the_bottom_and_stays_clear_of_the_indicator():
    css = _arrangement_css()
    for arrangement in ("sheet", "auto"):
        sheet = _sheet_half(css, arrangement)

        assert "align-items: flex-end" in sheet, "the panel sits on the bottom edge"
        assert "width: 100%" in sheet and "max-width: none" in sheet, "full width"
        assert "border-radius: var(--radius-lg, 0.5rem) var(--radius-lg, 0.5rem) 0 0" in (
            sheet
        ), "square bottom corners: it is flush with the screen edge"
        assert "padding-bottom: var(--safe-area-bottom" in sheet
        assert "max-height: 90dvh" in sheet, "dvh tracks the keyboard and the URL bar"


def test_a_sheet_slides_in_from_the_edge():
    sheet = _sheet_half(_arrangement_css(), "sheet")

    assert "transform: translateY(100%)" in sheet, "closed: off the edge"
    assert ".ui-modal-open .ui-modal-panel" in sheet, "open: slid into place"
    assert "transform: translateY(0)" in sheet


def test_only_auto_becomes_a_sheet_at_compact():
    """``auto`` is a centred dialog until the breakpoint; an explicit arrangement is not
    gated on the breakpoint at all."""
    css = _arrangement_css()
    base, compact = css.split(compact_media(), 1)

    assert '[data-arrangement="auto"]' not in base, "a desktop keeps the centred dialog"
    assert '[data-arrangement="auto"]' in compact

    # `sheet` asked for its shape, so it docks everywhere …
    assert "align-items: flex-end" in _sheet_half(base, "sheet")
    # … and `dialog` never docks, so it needs no rule at all.
    assert '[data-arrangement="dialog"]' not in css


def test_fullscreen_fills_the_screen_and_drops_the_chrome():
    css = _arrangement_css()
    fullscreen = css.split('[data-arrangement="fullscreen"] .ui-modal-panel', 1)[1]

    assert "height: 100dvh" in fullscreen
    assert "border-radius: 0" in fullscreen
    assert "padding-top: var(--safe-area-top" in fullscreen
    assert "padding-bottom: var(--safe-area-bottom" in fullscreen


def test_the_arrangements_ship_after_the_main_stylesheet():
    """The additive block is what wins the `transform` tie against the scale rules."""
    main = Modal._get_style_string()
    assert '[data-arrangement="sheet"]' not in main
    assert "transform: translateY(100%)" not in main

    assert dict(Modal._get_extra_styles())["arrangements"].strip()
