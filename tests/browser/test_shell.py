"""M1.4 — the responsive shell, driven in a real browser.

The server suite can only assert the *contract*: one breakpoint source, sizing as custom
properties, an arrangement expressed purely in CSS. Whether the layout actually
rearranges — and whether it rearranges without disturbing hydration — is a rendering
question, so this lane drives the real client at a phone viewport and at a desktop one
and asserts both the arrangement each tier gets and a clean hydration report.

The fixture page is the scaffolded composition (``browser_app/components/shell_frame.py``):
if the frame needs app CSS to be phone-correct, these tests fail.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
SHELL_URL = "/shell"

ACTIVITY_BAR = ".shell-activity-bar"
SIDEBAR = ".shell-sidebar"
MAIN = ".shell-main-container"
SPLITTER = ".shell-splitter"
STATUS_BAR = ".shell-status-bar"
TITLE_BAR = ".shell-title-bar"
TOGGLE = ".drawer-toggle .shell-sidebar-trigger"

_COMPACT_QUERY = "(max-width: 767px)"
_REGULAR_QUERY = "(min-width: 768px) and (max-width: 1023px)"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _open_shell(page, base_url, timeout):
    page.goto(base_url + SHELL_URL, wait_until="domcontentloaded")
    page.wait_for_selector(MAIN, timeout=timeout)
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    report = page.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report
    return report


def _box(page, selector):
    return page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            if (!el) return null;
            const r = el.getBoundingClientRect();
            return { x: r.x, y: r.y, width: r.width, height: r.height,
                     right: r.right, bottom: r.bottom };
        }""",
        selector,
    )


def _display(page, selector):
    return page.evaluate(
        "(sel) => getComputedStyle(document.querySelector(sel)).display", selector
    )


def _wait_settled(page, selector, predicate, timeout):
    """Wait until *selector*'s rect satisfies *predicate* with its slide finished.

    The drawer animates ``left``/``right`` over 0.25s, so a wait that only checks
    the rect can hand a mid-transition value to the near-exact assertions below.
    Requiring the transition to have stopped (``getAnimations`` also reports
    finished ones, hence the ``playState`` test) makes the read deterministic.
    """
    page.wait_for_function(
        f"""() => {{
            const el = document.querySelector("{selector}");
            if (!el) return false;
            if (el.getAnimations().some(a => a.playState === "running")) return false;
            const r = el.getBoundingClientRect();
            return {predicate};
        }}""",
        timeout=timeout,
    )


def test_compact_viewport_rearranges_the_workbench(app_server, mobile_context, request):
    timeout = _timeout_ms(request)
    page = mobile_context("iphone").new_page()
    _open_shell(page, app_server, timeout)

    # The viewport really is in the compact tier, and the tier is what CSS keys on.
    assert page.evaluate(f"() => matchMedia('{_COMPACT_QUERY}').matches") is True
    assert page.evaluate(f"() => matchMedia('{_REGULAR_QUERY}').matches") is False

    main = _box(page, MAIN)
    bar = _box(page, ACTIVITY_BAR)
    title = _box(page, TITLE_BAR)
    width = page.evaluate("() => window.innerWidth")

    # Title bar shrinks to the compact app bar.
    assert title["height"] == pytest.approx(44, abs=1.5), title

    # The primary surface comes first and fills the width...
    assert main["width"] == pytest.approx(width, abs=1.5), (main, width)

    # ...and the rail is now the bottom navigation, spanning the width below it.
    assert bar["y"] >= main["bottom"] - 1, (bar, main)
    assert bar["width"] == pytest.approx(width, abs=1.5), (bar, width)

    # Nothing is left over from the desktop arrangement.
    assert _display(page, SPLITTER) == "none"
    assert _display(page, STATUS_BAR) == "none"

    # The docked sidebar is out of the flow, parked off the left edge.
    sidebar = _box(page, SIDEBAR)
    assert sidebar["right"] <= 1, sidebar

    # No horizontal overflow: the frame fits the phone.
    assert page.evaluate(
        "() => document.documentElement.scrollWidth <= window.innerWidth + 1"
    ) is True


def test_compact_drawer_opens_and_closes(app_server, mobile_context, request):
    timeout = _timeout_ms(request)
    page = mobile_context("iphone").new_page()
    _open_shell(page, app_server, timeout)

    closed = _box(page, SIDEBAR)
    assert closed["right"] <= 1, closed

    # The title bar's toggle opens the drawer at this tier.
    page.tap(TOGGLE, timeout=timeout)
    _wait_settled(page, SIDEBAR, "r.x >= 0", timeout)
    opened = _box(page, SIDEBAR)
    assert opened["x"] == pytest.approx(0, abs=1.5), opened
    assert opened["width"] <= page.evaluate("() => window.innerWidth"), opened

    # The backdrop covers the page behind the panel, so a tap outside the drawer
    # lands on it and closes the drawer.
    page.mouse.click(page.evaluate("() => window.innerWidth - 8"), opened["y"] + 8)
    _wait_settled(page, SIDEBAR, "r.right <= 1", timeout)


def test_regular_viewport_keeps_the_desktop_frame(app_server, page, request):
    timeout = _timeout_ms(request)
    _open_shell(page, app_server, timeout)

    assert page.evaluate(f"() => matchMedia('{_COMPACT_QUERY}').matches") is False

    bar = _box(page, ACTIVITY_BAR)
    main = _box(page, MAIN)
    sidebar = _box(page, SIDEBAR)
    title = _box(page, TITLE_BAR)

    # The rail is a vertical strip on the left, then the sidebar, then the surface.
    assert bar["right"] <= sidebar["x"] + 1, (bar, sidebar)
    assert sidebar["right"] <= main["x"] + 1, (sidebar, main)
    assert bar["height"] > bar["width"]

    # The desktop chrome is intact: full-height title bar, live divider, status bar.
    assert title["height"] == pytest.approx(48, abs=1.5), title
    assert _display(page, SPLITTER) != "none"
    assert _display(page, STATUS_BAR) == "flex"


@pytest.mark.parametrize("device", ["iphone", "android"])
def test_drawer_is_closed_on_first_paint(app_server, mobile_context, device, request):
    """A phone must not open with a panel covering the page (the neutral drawer state)."""
    timeout = _timeout_ms(request)
    page = mobile_context(device).new_page()
    _open_shell(page, app_server, timeout)

    assert page.get_attribute(SIDEBAR, "data-drawer") == "closed"
    assert _box(page, SIDEBAR)["right"] <= 1
