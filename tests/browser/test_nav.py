"""M2.1 (3.1) — ``ui-nav``: one declaration, two arrangements, in a real browser.

The server suite can assert the *contract* (a compact block that docks, sizes from the
page scale, active state derived from the request path). Whether the *same* element is an
inline header row on a desktop and a strip pinned to the bottom edge on a phone is a
rendering question, so this lane drives both viewports and asserts the geometry each one
gets — plus a clean hydration report at both.

The fixture page is the site paradigm (``browser_app/components/nav_panel.py``): a
``shell-header`` holding a brand and one ``ui-nav``. If docking needed app CSS, these
tests fail.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
NAV_URL = "/nav"

NAV = ".ui-nav"
HEADER = ".shell-header"
ACTIVE = ".ui-nav-item.ui-nav-item-active"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _open(page, base_url, timeout):
    page.goto(base_url + NAV_URL, wait_until="domcontentloaded")
    page.wait_for_selector(NAV, timeout=timeout)
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    report = page.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report
    return report


def _box(page, selector):
    """The element's border box plus its used position scheme."""
    return page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            const r = el.getBoundingClientRect();
            return {
                top: r.top,
                bottom: r.bottom,
                left: r.left,
                right: r.right,
                height: r.height,
                position: getComputedStyle(el).position,
            };
        }""",
        selector,
    )


def test_the_nav_is_an_inline_row_in_the_header_on_a_desktop(
    app_server, page, request
):
    timeout = _timeout_ms(request)
    _open(page, app_server, timeout)

    nav = _box(page, NAV)
    header = _box(page, HEADER)

    assert nav["position"] != "fixed", nav
    assert header["top"] <= nav["top"], (header, nav)
    assert nav["bottom"] <= header["bottom"] + 1, (header, nav)


def test_the_same_element_docks_to_the_bottom_edge_on_a_phone(
    app_server, mobile_context, request
):
    timeout = _timeout_ms(request)
    phone = mobile_context("iphone").new_page()
    _open(phone, app_server, timeout)

    nav = _box(phone, NAV)
    viewport = phone.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")

    assert nav["position"] == "fixed", nav
    assert nav["left"] <= 1 and nav["right"] >= viewport["w"] - 1, (nav, viewport)
    assert abs(nav["bottom"] - viewport["h"]) <= 1, (nav, viewport)


def test_the_current_page_is_highlighted_without_app_wiring(
    app_server, mobile_context, request
):
    """Derived from ``$router.current_path``, so SSR renders it already highlighted."""
    timeout = _timeout_ms(request)
    phone = mobile_context("iphone").new_page()
    _open(phone, app_server, timeout)

    active = phone.evaluate(
        "(sel) => document.querySelector(sel).getAttribute('href')", ACTIVE
    )
    assert active == NAV_URL, active


def test_the_frame_reserves_the_strip_the_docked_nav_covers(
    app_server, mobile_context, request
):
    """The bar floats over the page, so something must reserve the space it takes.

    A custom property only inherits downwards, so the *nav* publishes the height at the
    document root and the *frame* reserves it — this asserts both halves at once, by
    checking the page's last content still clears the bar.
    """
    timeout = _timeout_ms(request)
    phone = mobile_context("iphone").new_page()
    _open(phone, app_server, timeout)

    # The nav published the strip's height at the root — a custom property's computed
    # value is the token sequence, so read it as text rather than as a number.
    published = phone.evaluate(
        "() => getComputedStyle(document.documentElement)"
        ".getPropertyValue('--shell-bottom-inset').trim()"
    )
    assert "44px" in published, published

    # ... and the frame spent it: the footer clears the bar.
    reserved = phone.evaluate(
        "() => parseFloat(getComputedStyle("
        "document.querySelector('.shell-site')).paddingBottom)"
    )
    assert reserved >= 44, reserved

    phone.evaluate("() => window.scrollTo(0, document.documentElement.scrollHeight)")
    geometry = phone.evaluate(
        """() => ({
            footerBottom: document.querySelector('.shell-footer').getBoundingClientRect().bottom,
            viewport: window.innerHeight,
        })"""
    )
    assert geometry["footerBottom"] <= geometry["viewport"] - reserved + 1, geometry
