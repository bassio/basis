"""M2.1 (4) — the overlay arrangements, in a real browser.

The server suite pins the *rules* (a sheet restates the four offsets, the compact half is
gated on the breakpoint). Where a box actually lands is a rendering question those rules
cannot answer, so this lane opens the same declaration at two viewports and measures it:

* on a desktop every overlay stays anchored to its host — a centred dialog, a menu beside
  the pointer, a drop-down palette, a stack in the corner;
* on a phone the dialog and the menu are flush with the bottom edge and span the width,
  the palette takes the whole screen, and the toast strip spans the width above the page
  gutter.

One page holds all four overlays, so each viewport costs a single boot.

The fixture page (``browser_app/components/overlay_panel.py``) declares ``auto`` and
nothing else: if an arrangement needed app CSS, these tests would fail.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
OVERLAY_URL = "/overlays"

MODAL_PANEL = ".ui-modal-panel"
MENU = ".ui-context-menu"
PALETTE_DIALOG = ".ui-palette-dialog"
TOAST_STRIP = ".ui-toast-stack"

#: The compact scope's ``--page-gutter``, which the bottom toast strip pads by.
COMPACT_GUTTER_PX = 16.0


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _open(target, base_url, timeout):
    """Open the fixture page and assert the SSR tree was adopted cleanly."""
    target.goto(base_url + OVERLAY_URL, wait_until="domcontentloaded")
    target.wait_for_selector(MODAL_PANEL, timeout=timeout)
    target.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    report = target.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report
    return report


def _box(target, selector):
    """The element's border box plus the used values that place it."""
    return target.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            const r = el.getBoundingClientRect();
            const s = getComputedStyle(el);
            return {
                top: r.top,
                bottom: r.bottom,
                left: r.left,
                right: r.right,
                width: r.width,
                height: r.height,
                position: s.position,
                paddingBottom: parseFloat(s.paddingBottom),
            };
        }""",
        selector,
    )


def test_a_desktop_keeps_every_overlay_anchored_to_its_host(app_server, page, request):
    _open(page, app_server, _timeout_ms(request))
    viewport = page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")

    modal = _box(page, MODAL_PANEL)
    assert modal["width"] < viewport["w"] - 1, "a dialog, not a sheet"
    assert modal["top"] > 1 and modal["bottom"] < viewport["h"] - 1, (modal, viewport)

    menu = _box(page, MENU)
    assert menu["width"] < viewport["w"] / 2, "as wide as its items, not as the screen"
    assert menu["bottom"] < viewport["h"] - 1, "not docked to the bottom edge"

    palette = _box(page, PALETTE_DIALOG)
    assert palette["top"] > 1, "a drop-down, not the whole screen"
    assert palette["bottom"] < viewport["h"] - 1, (palette, viewport)

    strip = _box(page, TOAST_STRIP)
    assert strip["right"] < viewport["w"] - 1, "inset from the right edge"
    assert strip["bottom"] < viewport["h"] - 1, "inset from the bottom edge"


def test_a_phone_lands_the_overlays_on_the_edges_a_thumb_reaches(
    app_server, mobile_context, request
):
    target = mobile_context("iphone").new_page()
    _open(target, app_server, _timeout_ms(request))
    viewport = target.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")

    # The dialog and the menu become bottom sheets: full width, flush with the edge.
    for selector in (MODAL_PANEL, MENU):
        box = _box(target, selector)
        assert box["left"] <= 1 and box["right"] >= viewport["w"] - 1, (selector, box)
        assert abs(box["bottom"] - viewport["h"]) <= 1, (selector, box, viewport)

    # The palette takes the whole screen, where the on-screen keyboard would otherwise
    # fight it for the space.
    palette = _box(target, PALETTE_DIALOG)
    assert abs(palette["top"]) <= 1 and abs(palette["bottom"] - viewport["h"]) <= 1, palette
    assert palette["left"] <= 1 and palette["right"] >= viewport["w"] - 1, palette

    # The toasts span the width, sitting above the page gutter rather than over it.
    strip = _box(target, TOAST_STRIP)
    assert strip["position"] == "fixed", strip
    assert strip["left"] <= 1 and strip["right"] >= viewport["w"] - 1, (strip, viewport)
    assert abs(strip["bottom"] - viewport["h"]) <= 1, (strip, viewport)
    assert strip["paddingBottom"] >= COMPACT_GUTTER_PX - 0.5, strip
