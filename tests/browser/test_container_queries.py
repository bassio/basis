"""M2.1 (5.0) — the container-query spike: can a component answer its own box?

The viewport contract (``compact_block``) is one axis; ``container_block`` is the other,
and this lane is where the second was measured before it was adopted. Three claims, each
one a fact about a real page rather than about the spec:

1. a container query resolves through this architecture — the querying element sits behind
   a ``display: contents`` host, which is what every Basis component renders;
2. the same declaration yields two different layouts **on one page** (a list in a 240px
   sidebar is not the list in a 1040px pane), which no media query can express;
3. declaring the container costs the box nothing **when its width is definite**, and
   collapses it when it is not — which is why the framework names no container of its own
   and each caller opts in where it knows the width.

The fixture (``browser_app/components/container_panel.py``) carries both a contained and an
uncontained workbench row, so the cost is an A/B rather than a claim.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
CONTAINER_URL = "/container"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _open(target, base_url, timeout):
    target.goto(base_url + CONTAINER_URL, wait_until="domcontentloaded")
    target.wait_for_selector(".spike-probe", timeout=timeout)
    target.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    report = target.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report
    return report


MEASURE = """() => {
    const box = (sel) => {
        const r = document.querySelector(sel).getBoundingClientRect();
        return {w: Math.round(r.width * 100) / 100, h: Math.round(r.height * 100) / 100};
    };
    const matched = (sel) =>
        getComputedStyle(document.querySelector(sel), "::after").content;
    const plain = ".spike-workbench:not(.spike-workbench--contained)";
    const contained = ".spike-workbench--contained";
    return {
        viewport: {w: window.innerWidth, h: window.innerHeight},
        narrowContainer: box(".spike-narrow"),
        narrowMatched: matched('[data-probe="narrow"]'),
        wideMatched: matched('[data-probe="wide"]'),
        bothConditions: box(".spike-both"),
        shrinkPlain: box(".spike-plain"),
        shrinkContained: box(".spike-contained"),
        sidebar: box(`${plain} .shell-sidebar`),
        plainSidebarMatched: matched('[data-probe="sidebar"]'),
        pane: box(`${plain} .shell-pane`),
        containedSidebar: box(`${contained} .shell-sidebar`),
        containedSidebarMatched: matched('[data-probe="sidebar-c"]'),
        containedPane: box(`${contained} .shell-pane`),
        containedPaneMatched: matched('[data-probe="pane-c"]'),
    };
}"""

NARROW = '"narrow"'
NONE = '"neither"'


def test_a_container_answers_the_box_rather_than_the_viewport(app_server, page, request):
    _open(page, app_server, _timeout_ms(request))
    measured = page.evaluate(MEASURE)

    # One page, two boxes, one declaration: the narrow box takes the compact layout and the
    # wide one keeps the default, at the same viewport.
    assert measured["narrowMatched"] == NARROW, measured
    assert measured["wideMatched"] == NONE, measured

    # A shell part keeps the width it declares *and* answers it, so a component can be
    # compact inside a narrow sidebar without asking the device anything.
    assert measured["containedSidebar"]["w"] == measured["sidebar"]["w"], measured
    assert measured["containedPane"]["w"] == measured["pane"]["w"], measured
    assert measured["containedSidebarMatched"] == NARROW, measured
    assert measured["containedPaneMatched"] == NONE, measured
    assert measured["sidebar"]["w"] == pytest.approx(240, abs=0.5), measured
    assert measured["pane"]["w"] == pytest.approx(1040, abs=0.5), measured

    # The uncontained row declares no container, so no query of it can fire — the control
    # that makes the rows above a comparison rather than an assumption.
    assert measured["plainSidebarMatched"] == NONE, measured

    # Definite widths survive containment; a content-sized box sizes as if it were empty.
    # That is why the framework names no container of its own: opting in is the caller's
    # decision, made where the width is known.
    assert measured["shrinkPlain"]["w"] > 100, measured
    assert measured["shrinkContained"]["w"] == 0, measured


def test_the_nested_form_needs_both_conditions(app_server, mobile_context, request):
    """A container rule inside a media rule is how the two scopes combine."""
    target = mobile_context("iphone").new_page()
    _open(target, app_server, _timeout_ms(request))
    phone = target.evaluate(MEASURE)

    assert phone["shrinkContained"]["w"] == 0, phone
    assert phone["narrowMatched"] == NARROW, phone
    # On a phone the pane is narrow too: the *box* answers, whatever the device is.
    assert phone["containedPaneMatched"] == NARROW, phone
    # The drawer keeps its own width — containment is inert here as well.
    assert phone["containedSidebar"]["w"] == pytest.approx(320, abs=0.5), phone
    # Both conditions hold, so the doubly-gated rule fires. On a desktop the media half
    # never matches — which is what makes the nesting mean "a phone *and* a narrow box".
    assert phone["bothConditions"]["h"] == 44, phone
