"""M1.5 — the touch/pointer contract, driven in a real browser.

The server suite asserts the *text* of the rule: every hover rule is guarded, every
suppressed focus ring is replaced, coarse-pointer sizing goes through the theme token.
Whether those rules produce the right *behaviour* on a phone is a rendering question,
so this lane drives the real client under a coarse-pointer device descriptor (iPhone
13: ``hover: none``, ``pointer: coarse``) and asserts what a user would notice:

- a tap does not leave a control stuck in its hover look;
- the same control is finger-sized;
- a 16px glyph keeps its size while its hit area grows;
- keyboard focus still shows a ring.

The fixture page (``browser_app/components/touch_panel.py``) is the catalogue case
list: a Button, an interactive Icon, a closable Tab, and the ``$device`` fields.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
TOUCH_URL = "/touch"

BUTTON = ".ui-btn"
ICON = ".ui-icon.interactive"
TAB_CLOSE = ".tab-close"
CAPABILITY = ".touch-panel-capability"

HOVER_QUERY = "(hover: hover)"
COARSE_QUERY = "(pointer: coarse)"

#: The touch floor, restated here on purpose: this lane independently checks the
#: framework's number rather than reading it out of ``basis.shared.pointer``.
TOUCH_TARGET = 44


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _open_touch(page, base_url, timeout):
    page.goto(base_url + TOUCH_URL, wait_until="domcontentloaded")
    page.wait_for_selector(BUTTON, timeout=timeout)
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    report = page.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report
    return report


def _phone(mobile_context, app_server, request):
    page = mobile_context("iphone").new_page()
    _open_touch(page, app_server, _timeout_ms(request))
    return page


def _paint(page, selector):
    """What the control actually looks like: paint and box."""
    return page.evaluate(
        """(sel) => {
            const el = document.querySelector(sel);
            const cs = getComputedStyle(el);
            const r = el.getBoundingClientRect();
            return {
                background: cs.backgroundColor,
                boxShadow: cs.boxShadow,
                width: r.width,
                height: r.height,
            };
        }""",
        selector,
    )


def _settled(page, selector, timeout):
    """Wait for *selector*'s press feedback to finish animating."""
    page.wait_for_function(
        f"""() => !document.querySelector("{selector}")
                        .getAnimations()
                        .some(a => a.playState === "running")""",
        timeout=timeout,
    )


def test_phone_answers_the_capability_queries(mobile_context, app_server, request):
    """``$device`` is a *declared* query: the phone corrects the server's neutral."""
    page = _phone(mobile_context, app_server, request)

    answered = page.evaluate(
        """([hover, coarse]) => ({
            hover: matchMedia(hover).matches,
            coarse: matchMedia(coarse).matches,
        })""",
        [HOVER_QUERY, COARSE_QUERY],
    )
    assert answered == {"hover": False, "coarse": True}, answered

    # The server ships the desktop-safe neutral (True); hydration must replace it.
    page.wait_for_function(
        """() => document.querySelector('.touch-panel-capability')
                    .dataset.hover === 'False'"""
    )
    assert page.get_attribute(CAPABILITY, "data-pointer") == "coarse"


def test_a_tap_does_not_latch_hover_styling(mobile_context, app_server, request):
    """The sticky-hover bug: a guarded rule never applies on a touch device."""
    timeout = _timeout_ms(request)
    page = _phone(mobile_context, app_server, request)
    baseline = _paint(page, BUTTON)

    page.tap(BUTTON)
    page.wait_for_function(
        """() => document.querySelector('.touch-panel-capability')
                    .dataset.taps === '1'"""
    )
    _settled(page, BUTTON, timeout)
    after_tap = _paint(page, BUTTON)

    # Hover changes the fill and the shadow; a press may legitimately move the
    # button, so only the hover paint is compared here.
    assert after_tap["background"] == baseline["background"], (baseline, after_tap)
    assert after_tap["boxShadow"] == baseline["boxShadow"], (baseline, after_tap)


def test_touch_targets_are_finger_sized(mobile_context, app_server, request):
    page = _phone(mobile_context, app_server, request)

    button = _paint(page, BUTTON)
    icon = _paint(page, ICON)
    assert button["height"] >= TOUCH_TARGET, button
    assert icon["width"] >= TOUCH_TARGET and icon["height"] >= TOUCH_TARGET, icon


def test_tab_close_hit_area_grows_without_growing_the_glyph(
    mobile_context, app_server, request
):
    page = _phone(mobile_context, app_server, request)

    close = _paint(page, TAB_CLOSE)
    assert close["width"] < TOUCH_TARGET, close  # the visual stays small

    reaches = page.evaluate(
        """() => {
            const close = document.querySelector('.tab-close');
            const r = close.getBoundingClientRect();
            const probe = document.elementFromPoint(r.left - 8, r.top + r.height / 2);
            return probe ? !!probe.closest('.tab-close') : false;
        }"""
    )
    assert reaches, "8px left of the close glyph is outside its hit area"


def test_keyboard_focus_still_shows_a_ring(mobile_context, app_server, request):
    """The audit replaced the UA ring rather than deleting it."""
    page = _phone(mobile_context, app_server, request)

    page.keyboard.press("Tab")
    focused = page.evaluate(
        """() => {
            const el = document.activeElement;
            const cs = getComputedStyle(el);
            return {
                className: el.className,
                outlineStyle: cs.outlineStyle,
                outlineWidth: parseFloat(cs.outlineWidth) || 0,
            };
        }"""
    )
    assert "ui-btn" in focused["className"], focused
    assert focused["outlineStyle"] != "none", focused
    assert focused["outlineWidth"] >= 2, focused
