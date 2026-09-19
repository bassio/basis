"""A loop child keeps its tree: one row component, both loop shapes.

The server renders a row per item, and the client adopts that markup. Adoption is what
makes the row's *own* bindings and listeners point at the live document: a row that
renders its value with its own binding cannot follow anything after load unless its
subtree was adopted, and its listener is a no-op for the same reason.

Shape one writes the loop on the component element; shape two wraps the component in a
plain element, which is how a row with anything of its own inside it is written — a
``ui-list-item`` holding a link, as the website's docs nav does.

Three claims per shape, all of them the row component's own:

* a store-driven prop moves (the row's binding is live);
* a loop re-run reaches it (the reconcile path pushes every prop again);
* its listener still fires, and fires once — a doubled adoption would attach it twice.

The store-driven prop is the claim the adoption pass and the item's prop wiring decide.
"""

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
LOOPS_URL = "/loops"

SHAPE_ONE = "loops-shape-one"
SHAPE_TWO = "loops-shape-two"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


def _open(page, base_url, timeout):
    """Load the fixture and return the hydration report, asserted clean."""
    page.goto(base_url + LOOPS_URL, wait_until="domcontentloaded")
    page.wait_for_selector(f".{SHAPE_ONE} .loop-row", timeout=timeout)
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    report = page.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report
    return report


def _rows(page, section):
    """Each row as ``[selected, label, taps]`` — all three owned by the row component."""
    return page.eval_on_selector_all(
        f".{section} .loop-row",
        """(els) => els.map((el) => [
            el.getAttribute('data-selected'),
            el.querySelector('.loop-row-label')?.textContent,
            el.querySelector('.loop-row-tap')?.textContent.trim(),
        ])""",
    )


def test_a_store_change_moves_a_looped_row_component_after_hydration(
    app_server, page, request
):
    """The row's own prop binding follows a store change once the row is adopted —
    whichever way the loop is written."""
    timeout = _timeout_ms(request)
    _open(page, app_server, timeout)

    # A branch neither side renders: its loop children have no SSR counterpart, and the
    # clean report asserted by _open is the claim — no row of theirs reaches the page.
    assert _rows(page, "loops-hidden") == []

    expected = [
        ["true", "Alpha", "0"],
        ["false", "Beta", "0"],
        ["false", "Gamma", "0"],
    ]
    assert _rows(page, SHAPE_ONE) == expected
    assert _rows(page, SHAPE_TWO) == expected

    page.click(".pick-second")
    page.wait_for_function(
        f"""() => document.querySelector(
            '.{SHAPE_TWO} .loops-wrapper:nth-child(2) .loop-row')?.getAttribute('data-selected') === 'true'""",
        timeout=timeout,
    )

    moved = [
        ["false", "Alpha", "0"],
        ["true", "Beta", "0"],
        ["false", "Gamma", "0"],
    ]
    assert _rows(page, SHAPE_ONE) == moved
    assert _rows(page, SHAPE_TWO) == moved
    # Still hydrated, and still not a fallback re-render.
    report = page.evaluate(f"() => window.{REPORT_GLOBAL}")
    assert not report.get("fallback"), report


def test_a_loop_re_run_keeps_the_row_component_live_in_both_shapes(
    app_server, page, request
):
    """A re-run reaches the child too: the reconcile path pushes every prop again."""
    timeout = _timeout_ms(request)
    _open(page, app_server, timeout)

    page.click(".pick-second")
    page.click(".add-row")
    page.wait_for_function(
        f"() => document.querySelectorAll('.{SHAPE_ONE} .loop-row').length === 4",
        timeout=timeout,
    )

    expected = [
        ["false", "Alpha", "0"],
        ["true", "Beta", "0"],
        ["false", "Gamma", "0"],
        ["false", "Extra 3", "0"],
    ]
    assert _rows(page, SHAPE_ONE) == expected
    assert _rows(page, SHAPE_TWO) == expected


def test_a_row_component_keeps_its_own_listener_after_hydration(
    app_server, page, request
):
    """The row's own handler is attached to the live node — and attached once.

    ``taps`` is the row's local state, so the text it renders is also the count of live
    listeners that fired: ``1`` after one click, and ``2`` if adoption ran twice.
    """
    timeout = _timeout_ms(request)
    _open(page, app_server, timeout)

    page.click(f".{SHAPE_ONE} .loops-host:first-child .loop-row-tap")
    page.click(f".{SHAPE_TWO} .loops-wrapper:first-child .loop-row-tap")
    page.wait_for_function(
        f"""() => document.querySelector(
            '.{SHAPE_TWO} .loops-wrapper:first-child .loop-row-tap')?.textContent.trim() === '1'""",
        timeout=timeout,
    )

    assert [row[2] for row in _rows(page, SHAPE_ONE)] == ["1", "0", "0"]
    assert [row[2] for row in _rows(page, SHAPE_TWO)] == ["1", "0", "0"]
