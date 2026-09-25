"""Real-browser HMR state preservation and rebuilt interaction."""

import json
import urllib.request

import pytest


pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def test_html_reload_preserves_state_and_rebuilds_live_bindings(
    app_server, page, request
):
    timeout = _timeout_ms(request)
    page_errors = []
    page.on("pageerror", lambda error: page_errors.append(str(error)))

    page.goto(app_server + "/", wait_until="domcontentloaded")
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    page.click(".counter .inc")
    page.wait_for_function(
        "() => document.querySelector('.counter .count')?.textContent === 'Count: 1'",
        timeout=15000,
    )

    template = """
        <div class="counter reloaded">
            <span class="count">Reloaded: {count}</span>
            <button class="inc" type="button" onclick="{increment}">Increment</button>
            <browser-context></browser-context>
        </div>
    """
    payload = json.dumps({
        "type": "hmr",
        "ext": "html",
        "file": "counter.html",
        "module": "browser_app.components.counter",
        "component_class": "Counter",
        "content": template,
    }).encode()
    http_request = urllib.request.Request(
        app_server + "/__test__/hmr",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(http_request, timeout=15) as response:
        assert json.load(response)["connections"] >= 1

    page.wait_for_function(
        "() => document.querySelector('.counter.reloaded .count')?.textContent === 'Reloaded: 1'",
        timeout=15000,
    )
    page.click(".counter.reloaded .inc")
    page.wait_for_function(
        "() => document.querySelector('.counter.reloaded .count')?.textContent === 'Reloaded: 2'",
        timeout=15000,
    )

    report = page.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report
    assert page_errors == []