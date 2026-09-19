"""M2.1 (5.1) — the new families, measured in a real browser.

The server suite can assert the contract of each family (which rules exist, which
properties carry the geometry). Whether a box actually *lands* where the arrangement
says is a rendering question, so this lane drives both viewports over one fixture page
holding every new family and asserts the geometry each viewport gets.

One page, one test per viewport: the lane costs a Pyodide boot per page, and the boot is
the expensive part, not the assertions.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
FAMILIES_URL = "/families"

SLIDER = ".ui-slider-input"
STEPPER_BUTTON = ".ui-stepper-button"
SEGMENT = ".ui-segmented-item"
SEGMENTED = ".ui-segmented"
LIST_ROW = 'ui-list-item .ui-list-row[data-arrangement="row"]'
LIST_LINK = "ui-list-item .ui-list-link"
TOGGLE_ROW = ".switch-container"
FAB = ".ui-fab"
NAV = ".ui-nav"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _open(page, base_url, timeout):
    page.goto(base_url + FAMILIES_URL, wait_until="domcontentloaded")
    page.wait_for_selector(FAB, timeout=timeout)
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    report = page.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report
    return report


def _phone(mobile_context, app_server, request):
    page = mobile_context("iphone").new_page()
    _open(page, app_server, _timeout_ms(request))
    return page


def _box(page, selector):
    return page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return {top: r.top, bottom: r.bottom, left: r.left, right: r.right,
                    width: r.width, height: r.height,
                    position: getComputedStyle(el).position};
        }""",
        selector,
    )


def test_the_families_are_the_same_page_on_a_desktop(app_server, page, request):
    """The desktop idiom: dense rows, inline segments, no docking."""
    timeout = _timeout_ms(request)
    _open(page, app_server, timeout)

    row = _box(page, LIST_ROW)
    nav = _box(page, NAV)
    segment = _box(page, SEGMENT)
    fab = _box(page, FAB)

    assert row["height"] < 40, row
    assert nav["position"] != "fixed", nav
    assert segment["width"] < _box(page, SEGMENTED)["width"], (segment, _box(page, SEGMENTED))
    assert fab["position"] == "fixed", fab
    assert fab["width"] == fab["height"] == 56, fab
    # A desktop FAB sits one page gutter in from the corner, with nothing pinned under it.
    viewport = page.evaluate("() => ({w: window.innerWidth, h: window.innerHeight})")
    gutter = 24  # --page-gutter's desktop value (1.5rem)
    assert abs((viewport["h"] - fab["bottom"]) - gutter) <= 2, (fab, viewport)
    assert abs((viewport["w"] - fab["right"]) - gutter) <= 2, (fab, viewport)


def test_the_same_page_gives_a_phone_finger_sized_controls(
    app_server, mobile_context, request
):
    timeout = _timeout_ms(request)
    phone = _phone(mobile_context, app_server, request)

    for selector in (SLIDER, STEPPER_BUTTON, SEGMENT):
        box = _box(phone, selector)
        assert box["height"] >= 44, (selector, box)

    row = _box(phone, LIST_ROW)
    assert row["height"] >= 44, row

    toggle = _box(phone, TOGGLE_ROW)
    assert toggle["height"] >= 44, toggle


def test_the_segments_fill_the_width_on_a_phone(app_server, mobile_context, request):
    """Full width is the phone arrangement; the desktop leaves them content-sized."""
    timeout = _timeout_ms(request)
    phone = _phone(mobile_context, app_server, request)

    segmented = _box(phone, SEGMENTED)
    parent = phone.evaluate(
        "() => document.querySelector('.families-body').getBoundingClientRect().width"
    )
    assert segmented["width"] >= parent - 1, (segmented, parent)


def test_the_fab_clears_whatever_the_page_pinned_to_the_bottom(
    app_server, mobile_context, request
):
    """The claim that needs a docked bar present: no overlap, no reliance on a constant.

    The nav publishes the strip's height and the FAB reads it, so this asserts the pair
    rather than either number.
    """
    timeout = _timeout_ms(request)
    phone = _phone(mobile_context, app_server, request)

    fab = _box(phone, FAB)
    nav = _box(phone, NAV)

    assert fab["width"] == fab["height"] == 56, fab
    assert nav["position"] == "fixed", nav
    assert fab["bottom"] <= nav["top"] + 1, (fab, nav)


def test_a_looped_row_renders_its_item_content(app_server, page, request):
    """A row per item, with the loop's own variable interpolated inside the row."""
    _open(page, app_server, _timeout_ms(request))

    texts = page.eval_on_selector_all(
        LIST_LINK, "(els) => els.map((el) => el.textContent.trim())"
    )
    assert texts == ["Groceries", "Standup notes", "Trip packing list"], texts


def test_the_list_draws_its_hairlines_between_rows(app_server, page, request):
    """Proven here rather than in the stylesheet: a list's rule has to reach a row's own
    box across the row's element."""
    _open(page, app_server, _timeout_ms(request))

    borders = page.eval_on_selector_all(
        "ui-list-item .ui-list-row",
        "(els) => els.map((el) => getComputedStyle(el).borderTopWidth)",
    )
    assert borders[0] == "0px", borders
    assert borders[1:] == ["1px"] * (len(borders) - 1), borders


def test_a_phone_reports_no_horizontal_overflow(
    app_server, mobile_context, request
):
    """Wide content makes a mobile browser zoom out and lie about the viewport width."""
    phone = _phone(mobile_context, app_server, request)

    measured = phone.evaluate(
        """() => ({
            inner: window.innerWidth,
            scroll: document.documentElement.scrollWidth,
            body: document.body.scrollWidth,
        })"""
    )
    assert measured["scroll"] <= measured["inner"], measured
    assert measured["body"] <= measured["inner"], measured
