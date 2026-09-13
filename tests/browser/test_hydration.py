"""The browser A/B gate: clean hydration + a live DOM update.

The server-side suite proves rendering and reactivity in Python; this proves the
*product* — that the same page, served SSR and hydrated by the Pyodide client in
a real browser, adopts the server tree with no mismatches and then updates the
DOM on interaction. This is the "client CI harness" the framework needs to be
trusted with SSR + hydration.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def test_ssr_adopts_cleanly_and_updates_live(app_server, page, request):
    timeout = _timeout_ms(request)

    page.goto(app_server + "/", wait_until="domcontentloaded")

    # The server rendered the counter — hydration has a real tree to adopt.
    page.wait_for_selector(".counter .count", timeout=timeout)
    assert page.inner_text(".counter .count") == "Count: 0"

    # The client boots (Pyodide) and emits its hydration report.
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    report = page.evaluate(f"() => window.{REPORT_GLOBAL}")

    assert report is not None
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report

    # A click re-renders through the client DAG — still hydrated, not a fallback.
    page.click(".counter .inc")
    page.wait_for_function(
        "() => document.querySelector('.counter .count')?.textContent === 'Count: 1'",
        timeout=15000,
    )
