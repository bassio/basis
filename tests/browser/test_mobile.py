"""M5.3b — mobile emulation: device viewports, touch, reduced-motion, offline.

Rides the M5.3a harness: the same fixture app + offline Pyodide client, now
driven through Playwright **device descriptors** (iPhone/Android viewport, DPR,
``has_touch``) with the mobile conditions the roadmap names — reduced-motion and
an offline toggle.

Both profiles run on the **Chromium** engine (the descriptor supplies the
viewport / UA / touch / DPR); a true WebKit lane is an M5.3c concern, as is a
real device.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
COUNT_SELECTOR = ".counter .count"
INC_SELECTOR = ".counter .inc"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _wait_hydrated(page, timeout):
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    return page.evaluate(f"() => window.{REPORT_GLOBAL}")


def _assert_clean(report):
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report


@pytest.mark.parametrize("device", ["iphone", "android"])
def test_mobile_touch_hydrates_cleanly_and_updates_live(
    app_server, mobile_context, device, request
):
    timeout = _timeout_ms(request)
    page = mobile_context(device).new_page()

    page.goto(app_server + "/", wait_until="domcontentloaded")
    page.wait_for_selector(COUNT_SELECTOR, timeout=timeout)
    assert page.inner_text(COUNT_SELECTOR) == "Count: 0"

    # Hydration is clean at the device viewport (the SSR tree is adopted).
    _assert_clean(_wait_hydrated(page, timeout))

    # The device descriptor gives us a touch-capable pointer.
    assert page.evaluate("() => navigator.maxTouchPoints > 0") is True

    # No horizontal overflow at the phone viewport.
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
    ) is True

    # A real touch tap re-renders through the client DAG (requires hasTouch).
    page.tap(INC_SELECTOR)
    page.wait_for_function(
        f"() => document.querySelector('{COUNT_SELECTOR}')?.textContent === 'Count: 1'",
        timeout=15000,
    )


def test_reduced_motion_is_emulated_and_hydration_stays_clean(
    app_server, mobile_context, request
):
    timeout = _timeout_ms(request)
    page = mobile_context("iphone", reduced_motion="reduce").new_page()

    page.goto(app_server + "/", wait_until="domcontentloaded")

    assert page.evaluate(
        "() => matchMedia('(prefers-reduced-motion: reduce)').matches"
    ) is True

    _assert_clean(_wait_hydrated(page, timeout))


def test_offline_toggle_keeps_client_reactivity_working(
    app_server, mobile_context, request
):
    timeout = _timeout_ms(request)
    context = mobile_context("android")
    page = context.new_page()

    page.goto(app_server + "/", wait_until="domcontentloaded")
    _assert_clean(_wait_hydrated(page, timeout))
    assert page.evaluate("() => navigator.onLine") is True

    # Cut the network mid-session — the mobile "edits on the train" case.
    context.set_offline(True)
    assert page.evaluate("() => navigator.onLine") is False

    # Client-side reactivity needs no server round-trip, so it still works.
    page.tap(INC_SELECTOR)
    page.wait_for_function(
        f"() => document.querySelector('{COUNT_SELECTOR}')?.textContent === 'Count: 1'",
        timeout=15000,
    )


# --- the page scale ----------------------------------

#: The catalogue fixture (``/touch``) renders a Button and a Tab, which is enough
#: to drive the M2.1 scale: one ``:root`` block decides control height, so no
#: component owns a viewport query to be phone-sized.
SCALE_URL = "/touch"
BUTTON_SELECTOR = ".ui-btn"
TAB_SELECTOR = ".ui-tab-container"

#: Restated on purpose: this lane independently checks the framework's numbers (the
#: dense desktop control height and the touch floor) rather than importing them.
DENSE_CONTROL_HEIGHT = 32
TOUCH_TARGET = 44


def _height(page, selector):
    return page.evaluate(
        "(sel) => document.querySelector(sel).getBoundingClientRect().height",
        selector,
    )


def _css_height(page, selector):
    """The *used* ``height`` value, which excludes a border the box adds on top."""
    return page.evaluate(
        "(sel) => getComputedStyle(document.querySelector(sel)).height",
        selector,
    )


def test_control_height_comes_from_the_page_scale(
    app_server, page, mobile_context, request
):
    """Dense on a desktop, finger-sized on a phone — from one scope, not two rules."""
    timeout = _timeout_ms(request)

    page.goto(app_server + SCALE_URL, wait_until="domcontentloaded")
    page.wait_for_selector(BUTTON_SELECTOR, timeout=timeout)
    _assert_clean(_wait_hydrated(page, timeout))

    phone = mobile_context("iphone").new_page()
    phone.goto(app_server + SCALE_URL, wait_until="domcontentloaded")
    phone.wait_for_selector(BUTTON_SELECTOR, timeout=timeout)
    _assert_clean(_wait_hydrated(phone, timeout))

    # A tab states its height outright, so both ends of the scale are exact — and
    # the desktop value is the one it had before the scale existed.
    assert _css_height(page, TAB_SELECTOR) == f"{DENSE_CONTROL_HEIGHT}px"
    assert _css_height(phone, TAB_SELECTOR) == f"{TOUCH_TARGET}px"

    # A button is padding-sized: the scale is a floor, so the desktop keeps its own
    # dense height and the phone is lifted to the touch target.
    desktop_button = _height(page, BUTTON_SELECTOR)
    assert DENSE_CONTROL_HEIGHT <= desktop_button < TOUCH_TARGET, desktop_button
    assert _height(phone, BUTTON_SELECTOR) >= TOUCH_TARGET
