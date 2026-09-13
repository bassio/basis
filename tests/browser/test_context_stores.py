"""The context data plane in a real browser: ``$device`` / ``$network`` live values.

The stores ship neutrals in ``#basis-initial-state`` so a server-rendered page and a
client-rendered page first paint the same thing; the probes read the real browser after
mount. What only a browser can prove is asserted here: the correction landed, it tracks
the viewport / pointer / motion / connectivity, and hydration stayed clean while it did.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
COUNTER_SELECTOR = ".counter .count"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _wait_hydrated(page, timeout):
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    return page.evaluate(f"() => window.{REPORT_GLOBAL}")


def _assert_clean(report):
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report


def _wait_text(page, selector, expected, timeout=15000):
    """Wait until *selector*'s text is *expected* (the probe's write is a DAG update)."""
    page.wait_for_function(
        """([sel, want]) => {
            const el = document.querySelector(sel);
            return !!el && el.textContent.trim() === want;
        }""",
        arg=[selector, expected],
        timeout=timeout,
    )


def _open(app_server, context, timeout):
    page = context.new_page()
    page.goto(app_server + "/", wait_until="domcontentloaded")
    page.wait_for_selector(COUNTER_SELECTOR, timeout=timeout)
    _assert_clean(_wait_hydrated(page, timeout))
    return page


def test_probes_fill_the_context_stores_after_mount(app_server, page, request):
    timeout = _timeout_ms(request)
    page = _open(app_server, page.context, timeout)

    width = page.evaluate("() => window.innerWidth")
    height = page.evaluate("() => window.innerHeight")

    _wait_text(page, ".ctx-width", str(width), timeout)
    _wait_text(page, ".ctx-height", str(height), timeout)

    # Desktop default viewport: a fine pointer, hover, no touch, honouring motion.
    assert page.inner_text(".ctx-pointer").strip() == "fine"
    assert page.inner_text(".ctx-hover").strip() == "True"
    assert page.inner_text(".ctx-touch").strip() == "False"
    assert page.inner_text(".ctx-reduced-motion").strip() == "False"

    # The neutral is the first paint; the probe's correction is a DAG update.
    assert page.inner_text(".ctx-online").strip() == "True"
    assert page.inner_text(".ctx-offline").strip() == "False"
    assert page.inner_text(".ctx-effective-type").strip() != ""

    _assert_clean(page.evaluate(f"() => window.{REPORT_GLOBAL}"))


def test_probes_track_the_viewport(app_server, page, request):
    timeout = _timeout_ms(request)
    page = _open(app_server, page.context, timeout)

    page.set_viewport_size({"width": 420, "height": 900})

    _wait_text(page, ".ctx-width", "420", timeout)
    _wait_text(page, ".ctx-height", "900", timeout)
    _wait_text(page, ".ctx-orientation", "portrait", timeout)

    page.set_viewport_size({"width": 1200, "height": 700})
    _wait_text(page, ".ctx-orientation", "landscape", timeout)

    _assert_clean(page.evaluate(f"() => window.{REPORT_GLOBAL}"))


def test_probes_report_a_touch_device(app_server, mobile_context, request):
    timeout = _timeout_ms(request)
    context = mobile_context("iphone")
    page = _open(app_server, context, timeout)

    expected_width = page.evaluate("() => window.innerWidth")
    _wait_text(page, ".ctx-width", str(expected_width), timeout)
    _wait_text(page, ".ctx-pointer", "coarse", timeout)
    _wait_text(page, ".ctx-touch", "True", timeout)
    _wait_text(page, ".ctx-orientation", "portrait", timeout)

    _assert_clean(page.evaluate(f"() => window.{REPORT_GLOBAL}"))


def test_probes_report_reduced_motion(app_server, mobile_context, request):
    timeout = _timeout_ms(request)
    context = mobile_context("iphone", reduced_motion="reduce")
    page = _open(app_server, context, timeout)

    # Declared on the store as a media query, so the shared listener answers it.
    _wait_text(page, ".ctx-reduced-motion", "True", timeout)

    _assert_clean(page.evaluate(f"() => window.{REPORT_GLOBAL}"))


def test_probes_track_connectivity(app_server, page, request):
    timeout = _timeout_ms(request)
    page = _open(app_server, page.context, timeout)

    page.context.set_offline(True)
    _wait_text(page, ".ctx-offline", "True", timeout)
    _wait_text(page, ".ctx-online", "False", timeout)

    page.context.set_offline(False)
    _wait_text(page, ".ctx-online", "True", timeout)

    _assert_clean(page.evaluate(f"() => window.{REPORT_GLOBAL}"))


def test_probes_release_on_pagehide_and_resume_on_pageshow(app_server, page, request):
    """The back/forward-cache cycle, through real event dispatch.

    ``pagehide`` releases the bindings (and the stores' client state with them), so a
    resize while frozen writes nothing; ``pageshow`` re-attaches and re-reads, so the
    value moved while frozen lands afterwards.
    """
    timeout = _timeout_ms(request)
    page = _open(app_server, page.context, timeout)

    page.set_viewport_size({"width": 700, "height": 900})
    _wait_text(page, ".ctx-width", "700", timeout)

    page.evaluate("() => window.dispatchEvent(new Event('pagehide'))")
    page.set_viewport_size({"width": 480, "height": 900})
    page.wait_for_timeout(400)  # proving a non-update needs a beat
    assert page.inner_text(".ctx-width").strip() == "700"

    page.evaluate(
        "() => window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))"
    )
    _wait_text(page, ".ctx-width", "480", timeout)

    _assert_clean(page.evaluate(f"() => window.{REPORT_GLOBAL}"))
