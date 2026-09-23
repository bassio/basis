"""M3.1/M3.2 — the installable app, in a real browser.

What this lane adds over the server suite: a service worker only exists when a browser
agrees to register one, only takes control when the response headers allow the scope it
was registered for, and only caches what its own router decides. None of that is
observable from Python.

Runs against ``pwa_app`` (a second fixture app) so the hydration and reactivity lanes
keep their pages worker-free.
"""

import time

import pytest

pytestmark = pytest.mark.browser

REPORT_GLOBAL = "__basisHydrationReport"
COUNT_SELECTOR = ".pwa .count"
INC_SELECTOR = ".pwa .inc"
CONTROLLED_SELECTOR = ".pwa .controlled"
READY_SELECTOR = ".pwa .ready"
UPDATE_SELECTOR = ".pwa .update"
MANIFEST_LINK = 'link[rel="manifest"]'

#: The runtime entries a boot cannot do without — used to check that "what the page
#: fetched is what got cached" is not a vacuous assertion.
REQUIRED_RUNTIME = (
    "pyodide/pyodide.mjs",
    "pyodide/pyodide.asm.wasm",
    "pyodide/python_stdlib.zip",
)

#: What the warm was asked to cache (the boot's own resources) versus what the caches
#: hold. Comparing the two is self-diagnosing: a miss names the byte and there is no
#: hand-maintained list to drift from what the client actually fetched.
RUNTIME_CACHED_JS = """async () => {
    const wanted = [...new Set(
        performance.getEntriesByType("resource")
            .map((entry) => new URL(entry.name).pathname)
            .filter((path) => path.startsWith("/pyscript/"))
    )];
    const cached = new Set();
    for (const name of await caches.keys()) {
        const cache = await caches.open(name);
        for (const request of await cache.keys()) {
            cached.add(new URL(request.url).pathname);
        }
    }
    return {wanted, missing: wanted.filter((path) => !cached.has(path))};
}"""

#: The same question as a boolean, for :func:`_wait_until`.
RUNTIME_READY_JS = f"async () => (await ({RUNTIME_CACHED_JS})()).missing.length === 0"


def _timeout_ms(request) -> int:
    return int(request.config.getoption("--browser-timeout") * 1000)


@pytest.fixture
def controlled_page(browser):
    """A page in its own context, already controlled by the worker.

    Offline state and CacheStorage are per context, so the cases that go offline cannot
    share the ``page`` fixture's context with a case that does not.
    """
    context = browser.new_context()
    try:
        yield context.new_page()
    finally:
        context.close()


def _wait_controlled(page, timeout):
    page.wait_for_function("() => !!navigator.serviceWorker.controller", timeout=timeout)


def _wait_until(page, expression: str, timeout: int):
    """Poll *expression* until it is truthy, invoking it and awaiting any promise.

    Deliberately not ``page.wait_for_function``: given an *async* predicate that method
    evaluates it as an expression, gets the function object back — which is truthy — and
    returns immediately, so the wait silently does nothing. ``page.evaluate`` does invoke
    and await it.
    """
    deadline = time.monotonic() + timeout / 1000
    while True:
        if page.evaluate(expression):
            return
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {expression[:60]}…")
        page.wait_for_timeout(250)


def _wait_runtime_cached(page, timeout) -> dict:
    """Wait until every runtime byte the boot fetched is in CacheStorage.

    The warm writes concurrently and off the critical path, so a test that only checked
    one file would prove the warm *started*. Waiting on "nothing the boot used is missing"
    is both the contract and the precondition for the offline cases.
    """
    _wait_until(page, RUNTIME_READY_JS, timeout)
    return page.evaluate(RUNTIME_CACHED_JS)


def _wait_hydrated(page, timeout):
    page.wait_for_function(f"() => !!window.{REPORT_GLOBAL}", timeout=timeout)
    return page.evaluate(f"() => window.{REPORT_GLOBAL}")


def _assert_clean(report):
    assert report["unhydrated_components"] == [], report
    assert report["unmatched_bindings"] == [], report
    assert not report.get("fallback"), report


def test_the_installed_app_hydrates_cleanly_with_its_manifest_link(
    pwa_server, page, request
):
    """The head's manifest link is served, rendered and *kept through hydration*.

    A link the client's ``$head.links`` did not agree with would either duplicate or
    disappear on adoption — the mismatch the hydration report catches.
    """
    timeout = _timeout_ms(request)
    page.goto(pwa_server + "/", wait_until="domcontentloaded")
    page.wait_for_selector(COUNT_SELECTOR, timeout=timeout)

    assert page.inner_text(COUNT_SELECTOR) == "Count: 0"
    assert page.evaluate(
        f"() => document.querySelectorAll('{MANIFEST_LINK}').length"
    ) == 1
    assert page.evaluate(
        f"() => document.querySelector('{MANIFEST_LINK}').href"
    ).endswith("/manifest.webmanifest")

    _assert_clean(_wait_hydrated(page, timeout))

    # …and the page is still live afterwards (the head contribution is not a one-off).
    page.click(INC_SELECTOR)
    page.wait_for_function(
        f"() => document.querySelector('{COUNT_SELECTOR}')?.textContent === 'Count: 1'",
        timeout=15000,
    )


def test_the_worker_takes_the_root_scope_and_the_store_sees_it(pwa_server, page, request):
    """Registration, the scope header, and the state mirror — the three together.

    ``registration.scope`` is ``/`` only because the route sends
    ``Service-Worker-Allowed: /``; a plugin-mounted script could not control the app. The
    ``.controlled`` marker then proves the client's ``controllerchange`` reached Python as
    reactive state (it is rendered by ``if="{$pwa.controlled}"``, so the node appearing is
    a DAG update, not a server render).
    """
    timeout = _timeout_ms(request)
    page.goto(pwa_server + "/", wait_until="domcontentloaded")
    _assert_clean(_wait_hydrated(page, timeout))

    # The server shipped the neutral, so nothing is rendered until the client corrects it.
    assert page.query_selector(CONTROLLED_SELECTOR) is None

    page.wait_for_function(
        "() => !!navigator.serviceWorker.controller", timeout=timeout
    )
    registration = page.evaluate(
        "async () => { const r = await navigator.serviceWorker.getRegistration();"
        " return r ? {scope: r.scope, script: r.active && r.active.scriptURL} : null; }"
    )
    assert registration is not None, "no registration"
    assert registration["scope"] == pwa_server + "/"
    assert registration["script"] == pwa_server + "/service-worker.js"

    page.wait_for_selector(CONTROLLED_SELECTOR, timeout=timeout)


def test_the_runtime_is_cached_but_not_precached(pwa_server, page, request):
    """The cache tiers, read out of CacheStorage.

    The shell is precached at install (so the app's own code works offline after one
    visit); the Pyodide runtime is not — it is 14 MB of the bundle — and it is *warmed*
    instead: the page tells the worker what its boot fetched, and the worker caches those
    entries. Without that the first visit would end with the interpreter in the HTTP cache
    and nothing in CacheStorage, so an offline reload would render the shell and then fail
    to start Python.
    """
    timeout = _timeout_ms(request)
    page.goto(pwa_server + "/", wait_until="domcontentloaded")
    _assert_clean(_wait_hydrated(page, timeout))
    _wait_controlled(page, timeout)

    buckets = page.evaluate("() => caches.keys()")
    assert any(name.startswith("basis-shell-") for name in buckets), buckets

    shell = page.evaluate(
        "async () => { const name = (await caches.keys()).find(n => n.startsWith('basis-shell-'));"
        " const cache = await caches.open(name); const keys = await cache.keys();"
        " return keys.map(r => new URL(r.url).pathname); }"
    )
    # The app's own code, the registration module, the fallback and the start page are the
    # shell.
    assert "/pwa_app/components/counter.py" in shell
    assert "/basis/plugins/mobile/pwa/register.js" in shell
    assert "/offline" in shell
    assert "/" in shell
    # …and no part of the 14 MB runtime is: it is warmed, not installed on someone's phone.
    assert not [url for url in shell if url.startswith("/pyscript/")], shell

    # The warm is asynchronous (the page hands the worker a list and moves on), so wait
    # for the bytes rather than for the message.
    state = _wait_runtime_cached(page, timeout)
    # The interpreter itself, not just its entry script: a boot needs the wasm and the
    # stdlib, and a warm that cached only `core.js` would look like success and still fail
    # offline. (Asserted on what the page *asked* for, so the check above cannot be
    # vacuously true.)
    for entry in REQUIRED_RUNTIME:
        assert any(path.endswith(entry) for path in state["wanted"]), state["wanted"]
    assert state["missing"] == []


def test_the_app_works_offline_after_one_visit(pwa_server, controlled_page, request):
    """The promise M3.2 exists for: one visit, then the app opens with no network.

    Both halves matter. The shell being cached is what makes the *document* load, and the
    warmed runtime is what makes it *boot* — a page that renders and then dies waiting for
    Python is the failure this asserts against. The click is the proof that Pyodide really
    started: a cached document alone renders the SSR markup and nothing else.
    """
    timeout = _timeout_ms(request)
    page = controlled_page
    page.goto(pwa_server + "/", wait_until="domcontentloaded")
    _assert_clean(_wait_hydrated(page, timeout))
    _wait_controlled(page, timeout)
    _wait_runtime_cached(page, timeout)

    page.context.set_offline(True)
    page.reload(wait_until="domcontentloaded")

    # The document itself comes straight out of the cache (the SSR markup is there before
    # any script runs) …
    page.wait_for_selector(COUNT_SELECTOR, timeout=timeout)
    assert page.inner_text(COUNT_SELECTOR) == "Count: 0"
    # … and then Python boots offline. The click is only meaningful once it has: bindings
    # are attached during hydration, so clicking earlier is clicking a dead page.
    _assert_clean(_wait_hydrated(page, timeout))
    page.click(INC_SELECTOR)
    page.wait_for_function(
        f"() => document.querySelector('{COUNT_SELECTOR}')?.textContent === 'Count: 1'",
        timeout=timeout,
    )


def test_a_route_that_was_never_cached_lands_on_the_fallback(
    pwa_server, controlled_page, request
):
    """The fallback document is the floor under an offline navigation.

    ``/second`` is never visited online, so there is no copy of it to serve and the worker
    has to answer with the precached fallback — which is why that document is precached,
    inlined and dependency-free.
    """
    timeout = _timeout_ms(request)
    page = controlled_page
    page.goto(pwa_server + "/", wait_until="domcontentloaded")
    _assert_clean(_wait_hydrated(page, timeout))
    _wait_controlled(page, timeout)

    page.context.set_offline(True)
    page.goto(pwa_server + "/second", wait_until="domcontentloaded")

    assert "offline" in page.inner_text("h1").lower()
    assert page.query_selector('a[href="/"]') is not None
    # Nothing of the app's own runtime was needed to render it.
    assert page.evaluate("() => document.querySelectorAll('script').length") == 0


def test_a_new_build_is_offered_and_applied(pwa_server, pwa_scratch, controlled_page, request):
    """The update prompt: a deploy becomes reactive state, and applying it reloads once.

    "A deploy" is a rewritten file in the mounted scratch dir, which moves the shell
    version and therefore the worker script's bytes — the same mechanism a real deploy
    uses, without editing this repository.
    """
    timeout = _timeout_ms(request)
    page = controlled_page
    page.goto(pwa_server + "/", wait_until="domcontentloaded")
    _assert_clean(_wait_hydrated(page, timeout))
    _wait_controlled(page, timeout)
    assert page.query_selector(READY_SELECTOR) is None

    (pwa_scratch / "probe.py").write_text(f"build = {time.time_ns()}\n")
    page.reload(wait_until="domcontentloaded")

    page.wait_for_selector(READY_SELECTOR, timeout=timeout)
    # A real reload is what proves the takeover, so leave a mark for it to erase.
    page.evaluate("() => { window.__beforeUpdate = true; }")
    page.click(UPDATE_SELECTOR)

    page.wait_for_function("() => !window.__beforeUpdate", timeout=timeout)
    page.wait_for_selector(CONTROLLED_SELECTOR, timeout=timeout)
    assert page.query_selector(READY_SELECTOR) is None


def test_the_api_is_never_cached(pwa_server, controlled_page, request):
    """A cached projection would turn a network failure into a stale success.

    The M3.3 offline mutation queue replays through ``/basis/api/**``, so a worker that
    answered those from a cache would not just be stale — it would be lying about a
    mutation having been sent.
    """
    timeout = _timeout_ms(request)
    page = controlled_page
    page.goto(pwa_server + "/", wait_until="domcontentloaded")
    _assert_clean(_wait_hydrated(page, timeout))
    _wait_controlled(page, timeout)

    # A successful call first: there is something a careless worker *could* have cached.
    assert page.evaluate(
        "async () => (await fetch('/basis/api/plugins')).status"
    ) == 200

    page.context.set_offline(True)

    assert page.evaluate(
        "async () => { try { await fetch('/basis/api/plugins'); return 'served'; }"
        " catch (error) { return 'failed'; } }"
    ) == "failed"
    cached = page.evaluate(
        "async () => { const found = [];"
        " for (const name of await caches.keys()) {"
        "   const cache = await caches.open(name);"
        "   for (const request of await cache.keys()) {"
        "     const path = new URL(request.url).pathname;"
        "     if (path.startsWith('/basis/api/')) found.push(path);"
        "   }"
        " } return found; }"
    )
    assert cached == []
