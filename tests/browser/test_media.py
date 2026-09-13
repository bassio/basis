"""Declared media queries in a real browser: attach after mount, track the viewport.

Only the browser can answer a media query, so the assertion that matters is that the
SSR neutral is adopted unchanged and then corrected live, without disturbing the
hydration report.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
NARROW = ".narrow-flag"
WIDE = ".wide-flag"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _wait_hydrated(page, timeout):
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    return page.evaluate(f"() => window.{REPORT_GLOBAL}")


def _assert_clean(report):
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report


def _wait_flag(page, selector, present, timeout=15000):
    state = "attached" if present else "detached"
    page.wait_for_selector(selector, state=state, timeout=timeout)


def test_media_queries_track_the_viewport(app_server, page, request):
    timeout = _timeout_ms(request)
    page.goto(app_server + "/", wait_until="domcontentloaded")
    page.wait_for_selector(".counter", timeout=timeout)

    # The desktop default viewport already agrees with both neutrals.
    assert page.query_selector(NARROW) is None
    assert page.query_selector(WIDE) is not None
    _assert_clean(_wait_hydrated(page, timeout))

    page.set_viewport_size({"width": 420, "height": 800})
    _wait_flag(page, NARROW, True)
    _wait_flag(page, WIDE, False)

    page.set_viewport_size({"width": 1280, "height": 800})
    _wait_flag(page, NARROW, False)
    _wait_flag(page, WIDE, True)

    # Resizing is a DAG update, not a structural divergence.
    _assert_clean(page.evaluate(f"() => window.{REPORT_GLOBAL}"))


def test_media_neutral_is_adopted_then_corrected_on_a_narrow_device(
    app_server, mobile_context, request
):
    timeout = _timeout_ms(request)
    page = mobile_context("iphone").new_page()

    page.goto(app_server + "/", wait_until="domcontentloaded")
    page.wait_for_selector(".counter", timeout=timeout)
    _assert_clean(_wait_hydrated(page, timeout))

    # 390px wide: both answers contradict their neutral, so the listener corrects
    # them after mount.
    _wait_flag(page, NARROW, True)
    _wait_flag(page, WIDE, False)
    _assert_clean(page.evaluate(f"() => window.{REPORT_GLOBAL}"))
