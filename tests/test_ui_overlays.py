"""
Tests for the overlay arrangements (``ui-context-menu``, ``ui-command-palette``,
``ui-toast-container``).

An overlay is a surface plus a decision about *where* it sits and how much of the screen
it may have. Each family declares that decision once, as ``arrangement``, and CSS resolves
it — so ``auto`` is a pointer-anchored menu on a desktop and a bottom-anchored action sheet
on a phone without a Python branch, and therefore with nothing for hydration to disagree
about.

The rules ship as additive blocks (``@extra_style``), i.e. *after* the family's main
stylesheet, so an app can restate an arrangement without copying the whole stylesheet.
"""
import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.styling import compact_media
from basis.shared.component import Component
from basis.shared.page import _synthesize_page
from basis.shared.reactive import state

# Registers the custom elements under test.
import basis.plugins.ui.command_palette.command_palette  # noqa: F401
import basis.plugins.ui.context_menu.context_menu  # noqa: F401
import basis.plugins.ui.toast.toast  # noqa: F401
from basis.plugins.ui.command_palette.command_palette import CommandPalette
from basis.plugins.ui.context_menu.context_menu import ContextMenu
from basis.plugins.ui.toast.toast import ToastContainer


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


def _arrangements(cls) -> str:
    """The additive block carrying every arrangement rule for *cls*."""
    blocks = dict(cls._get_extra_styles())
    assert "arrangements" in blocks, list(blocks)
    return blocks["arrangements"]


def _rule(css: str, selector: str) -> str:
    """Everything from *selector* on — including the rules that follow it."""
    assert selector in css, selector
    return css.split(selector, 1)[1]


def _halves(cls):
    """The (every-viewport, compact-only) halves of a family's arrangement rules."""
    css = _arrangements(cls)
    assert css.count(compact_media()) == 1, "one compact half, or the split is a guess"
    base, compact = css.split(compact_media(), 1)
    return base, compact


OVERLAYS = (
    (ContextMenu, "sheet"),
    (CommandPalette, "fullscreen"),
    (ToastContainer, "bottom"),
)


def test_every_overlay_defaults_to_auto():
    for cls, _explicit in OVERLAYS:
        assert cls.arrangement == "auto", cls.__name__


def test_every_arrangement_reaches_the_markup():
    class Root(Component):
        """
        <div class="root">
            <ui-context-menu arrangement="sheet" items="{items}"></ui-context-menu>
            <ui-command-palette arrangement="fullscreen"></ui-command-palette>
            <ui-toast-container arrangement="bottom"></ui-toast-container>
        </div>
        """
        items: list = state(
            default_factory=lambda: [{"label": "Rename", "action": "rename"}]
        )

    html = _render(Root, "/test_overlay_arrangements.py")

    assert 'data-arrangement="sheet"' in html
    assert 'data-arrangement="fullscreen"' in html
    assert 'data-arrangement="bottom"' in html


@pytest.mark.parametrize("cls,explicit", OVERLAYS)
def test_the_arrangement_rules_are_additive(cls, explicit):
    """An additive block is the layer an app can restate without copying the family."""
    main = cls._get_style_string()
    marker = f'[data-arrangement="{explicit}"]'

    assert marker in _arrangements(cls)
    assert marker not in main


@pytest.mark.parametrize("cls,explicit", OVERLAYS)
def test_an_explicit_arrangement_is_honoured_at_every_viewport(cls, explicit):
    """The "unless they want to" rule: only ``auto`` is gated on the breakpoint."""
    base, compact = _halves(cls)

    assert f'[data-arrangement="{explicit}"]' in base, "asked for its shape, so it keeps it"
    assert f'[data-arrangement="{explicit}"]' not in compact, "compact must not restate it"

    assert 'data-arrangement="auto"' not in base, "a desktop keeps the base arrangement"
    assert 'data-arrangement="auto"' in compact


def test_a_context_menu_sheet_ignores_the_pointer():
    css = _arrangements(ContextMenu)

    for arrangement in ("sheet", "auto"):
        sheet = _rule(css, f'.ui-context-menu[data-arrangement="{arrangement}"]')

        assert "left: 0" in sheet and "right: 0" in sheet, "spans the width"
        assert "top: auto" in sheet and "bottom: 0" in sheet, "flush with the bottom edge"
        assert "min-width: 0" in sheet, "the pointer-era minimum would overflow a phone"
        assert "max-height: 70dvh" in sheet, "dvh tracks the keyboard and the URL bar"
        assert "padding-bottom: var(--safe-area-bottom" in sheet, "clear of the indicator"
        assert "overflow-y: auto" in sheet, "a long menu scrolls rather than clips"


def test_a_pointer_menu_keeps_the_pointer_position():
    """``menu`` asks for the base component, so it needs no rule at all."""
    assert '[data-arrangement="menu"]' not in _arrangements(ContextMenu)


def test_a_fullscreen_palette_fills_the_screen_and_drops_the_chrome():
    css = _arrangements(CommandPalette)

    for arrangement in ("fullscreen", "auto"):
        rule = _rule(css, f'.ui-palette-overlay[data-arrangement="{arrangement}"]')

        assert "padding-top: 0" in rule, "the drop-down offset would leave a gap"

        dialog = rule.split(".ui-palette-dialog", 1)[1]
        assert "max-width: none" in dialog
        assert "height: 100dvh" in dialog and "max-height: 100dvh" in dialog
        assert "border-radius: 0" in dialog, "it touches every edge"
        assert "padding-top: var(--safe-area-top" in dialog
        assert "padding-bottom: var(--safe-area-bottom" in dialog


def test_a_dialog_palette_keeps_its_drop_down_shape():
    """``dialog`` asks for the base component, so it needs no rule at all."""
    assert '[data-arrangement="dialog"]' not in _arrangements(CommandPalette)


def test_the_bottom_toasts_span_the_gutter_and_clear_the_indicator():
    css = _arrangements(ToastContainer)

    for arrangement in ("bottom", "auto"):
        strip = _rule(css, f'.ui-toast-stack[data-arrangement="{arrangement}"]')

        assert "left: 0" in strip and "right: 0" in strip
        assert "bottom: 0" in strip, "flush with the bottom edge"
        assert "padding: var(--page-gutter, 1.5rem)" in strip, "the page scale, not a literal"
        assert (
            "padding-bottom: calc(var(--page-gutter, 1.5rem) + var(--safe-area-bottom"
            in strip
        ), "the indicator sits below the gutter, not over the last card"

        card = strip.split(".toast-body", 1)[1]
        assert "min-width: 0" in card, "a 320px minimum overflows a 390px phone"
        assert "max-width: none" in card, "the card spans the width it was given"


def test_a_corner_stack_keeps_its_corner():
    """``corner`` asks for the base component, so it needs no rule at all."""
    assert '[data-arrangement="corner"]' not in _arrangements(ToastContainer)


def test_the_toast_host_owns_no_box():
    """``display: contents`` on the host, geometry on the inner element.

    A host cannot carry an attribute its own template renders, so the prop only reaches
    the DOM because the box moved onto the element the template controls. The host is the
    scope root — ``:scope`` — and carries nothing but that transparency.
    """
    css = ToastContainer._get_style_string()
    assert "@scope (ui-toast-container)" in css

    host = css.split(":scope {", 1)[1].split("}", 1)[0]
    stack = css.split(".ui-toast-stack {", 1)[1].split("}", 1)[0]

    assert "display: contents" in host
    assert "position" not in host, "a box on the host would hide data-arrangement"
    assert "position: fixed" in stack
