"""Playwright client-browser harness.

These tests drive the *real* client — Pyodide/PyScript in a browser — so they are
opt-in, exactly like the benchmark suite:

    pytest tests/browser --browser

They assert the two things the server-side suite structurally cannot:

* **clean hydration** — the SSR tree is adopted with no unhydrated components,
  no unmatched bindings, and no fallback re-render; and
* **a live DOM update** — a click re-renders through the client DAG.

Requires ``playwright`` plus a browser binary:

    uv pip install playwright
    playwright install chromium

``BASIS_BROWSER`` selects the engine (``chromium`` by default); e.g.
``BASIS_BROWSER=firefox pytest tests/browser --browser``. Engine differences are what
this lane exists to catch — a client-only path that assumes a Chromium API (or a lazy
truthiness check on one) passes here and fails for a user.

The fixture app (``browser_app/``) boots under uvicorn as a subprocess and serves
the framework's offline vendored Pyodide, so the run is deterministic and needs
no network.
"""

import importlib.util
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

HERE = Path(__file__).parent
APP_MODULE = "browser_app:app"


def pytest_addoption(parser):
    parser.addoption(
        "--browser",
        action="store_true",
        default=False,
        help="Run the Playwright client-browser tests (skipped by default).",
    )
    parser.addoption(
        "--browser-timeout",
        type=float,
        default=90.0,
        help="Seconds to allow for Pyodide boot + hydration in the browser.",
    )


def _playwright_missing_reason() -> str | None:
    """``None`` when the playwright package is importable, else a skip reason.

    Deliberately does NOT start the driver here — a collection-time driver
    start/stop leaks pending Playwright tasks into teardown. Launch failures
    (e.g. chromium not installed) are handled by the ``browser`` fixture.
    """
    if importlib.util.find_spec("playwright") is None:
        return "playwright is not installed — run `uv pip install playwright`"
    return None


def pytest_collection_modifyitems(config, items):
    """Skip ``browser``-marked tests unless ``--browser`` (and Playwright) are usable."""
    browser_items = [item for item in items if "browser" in item.keywords]
    if not browser_items:
        return

    if not config.getoption("--browser"):
        skip = pytest.mark.skip(reason="browser test — run with `--browser` to enable")
        for item in browser_items:
            item.add_marker(skip)
        return

    reason = _playwright_missing_reason()
    if reason:
        skip = pytest.mark.skip(reason=reason)
        for item in browser_items:
            item.add_marker(skip)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="session")
def app_server():
    """Boot the fixture Basis app under uvicorn; yield its base URL."""
    port = _free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(HERE) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            APP_MODULE,
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "warning",
        ],
        cwd=str(HERE),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 60
    try:
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read().decode("utf-8", "replace") if proc.stdout else ""
                raise RuntimeError(f"fixture app exited during startup:\n{out}")
            try:
                with urllib.request.urlopen(base + "/", timeout=2) as resp:
                    if resp.status == 200:
                        ready = True
                        break
            except Exception:
                time.sleep(0.25)
        if not ready:
            raise RuntimeError("fixture app did not become ready within 60s")
        yield base
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()
        if proc.stdout is not None:
            proc.stdout.close()


@pytest.fixture(scope="session")
def _playwright_instance():
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()
    try:
        yield playwright
    finally:
        playwright.stop()


@pytest.fixture(scope="session")
def browser(_playwright_instance):
    engine = os.environ.get("BASIS_BROWSER", "chromium")
    try:
        instance = getattr(_playwright_instance, engine).launch()
    except Exception as exc:
        pytest.skip(f"could not launch {engine} — run `playwright install {engine}` ({exc})")
    try:
        yield instance
    finally:
        instance.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    try:
        yield context.new_page()
    finally:
        context.close()


# --- mobile emulation --------------------------------

#: Curated device profiles the harness exercises. Playwright ships 200+; these
#: two cover the two dominant phone platforms (a tall-notch iPhone and a current
#: Android). Each descriptor sets viewport + deviceScaleFactor + ``has_touch``.
MOBILE_DEVICES = {
    "iphone": "iPhone 13",
    "android": "Pixel 5",
}


@pytest.fixture(scope="session")
def device_matrix(_playwright_instance):
    """The resolved device descriptors, or skip when Playwright lacks them."""
    available = _playwright_instance.devices
    missing = [name for name in MOBILE_DEVICES.values() if name not in available]
    if missing:
        pytest.skip(f"Playwright device descriptor(s) unavailable: {missing}")
    return {key: dict(available[name]) for key, name in MOBILE_DEVICES.items()}


@pytest.fixture
def mobile_context(browser, device_matrix):
    """Factory for an emulated-device context.

    ``mobile_context("iphone")`` uses the descriptor's viewport /
    deviceScaleFactor / ``has_touch`` / mobile UA; keyword overrides layer on
    Playwright context options (e.g. ``reduced_motion="reduce"``), and the
    returned context supports ``set_offline(True)`` per test. Every context
    created here is closed at teardown.
    """
    created = []

    def _make(device: str, **overrides):
        options = dict(device_matrix[device])
        options.update(overrides)
        context = browser.new_context(**options)
        created.append(context)
        return context

    try:
        yield _make
    finally:
        for context in created:
            context.close()
