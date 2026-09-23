"""The app-shell service worker: its route, its headers, and its version.

The worker is generated per request, so the interesting contracts are:

* **the headers** — a root path with ``Service-Worker-Allowed: /`` (or the worker can only
  ever control the plugin's own directory) and ``no-cache`` (or an update can hide for a
  day), which is why these are asserted rather than assumed;
* **the version** — a new one whenever anything the browser already cached changed, and
  the *same* one when nothing did (a version that moves on every request would reinstall
  the shell on every navigation);
* **the tiers** — the shell is precached, the Pyodide runtime is deliberately not, and
  ``/basis/api/**`` is bypassed by the routing table.
"""
import json
import re

import pytest
from fastapi.testclient import TestClient

from basis.plugins.mobile import PwaStore
from basis.plugins.mobile.pwa import REGISTER_URL, SERVICE_WORKER_URL
from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page
from basis.shared.store import Store


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes
    Store._registry.clear()
    Store._store_blueprints.clear()


def _boot_app():
    app = Basis()
    app.bootstrap()

    class WorkerRoot(Component):
        template = "<div>hi</div>"

    class WorkerPage(Page):
        title = "worker"
        root_component = WorkerRoot

    app.include_page("/demo", page_cls=WorkerPage)
    return app


def _app(**declaration):
    PwaStore("pwa", **declaration)
    return _boot_app()


def _app_without_a_declaration():
    return _boot_app()


def _config(app) -> dict:
    """The ``const BASIS = {…}`` prelude the body is served with."""
    response = TestClient(app).get(SERVICE_WORKER_URL)
    assert response.status_code == 200
    match = re.search(r"^const BASIS = (\{.*\});$", response.text, re.MULTILINE)
    assert match, response.text[:400]
    return json.loads(match.group(1))


def _worker(app) -> str:
    response = TestClient(app).get(SERVICE_WORKER_URL)
    assert response.status_code == 200
    return response.text


def test_an_app_that_declared_nothing_has_no_worker():
    app = _app_without_a_declaration()
    assert TestClient(app).get(SERVICE_WORKER_URL).status_code == 404


def test_the_offline_switch_is_what_turns_the_worker_off():
    app = _app(offline=False)
    assert TestClient(app).get(SERVICE_WORKER_URL).status_code == 404
    # …and that is the *only* thing it turns off: the app is still installable.
    assert TestClient(app).get("/manifest.webmanifest").status_code == 200


def test_the_worker_is_served_root_scoped_and_revalidated():
    app = _app()
    response = TestClient(app).get(SERVICE_WORKER_URL)

    assert response.headers["service-worker-allowed"] == "/"
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["content-type"].startswith("application/javascript")

    again = TestClient(app).get(
        SERVICE_WORKER_URL, headers={"if-none-match": response.headers["etag"]}
    )
    assert again.status_code == 304


def test_the_worker_is_a_classic_script_that_owns_the_lifecycle():
    body = _worker(_app())

    # A classic script: no module syntax, so every engine can run it.
    assert "export " not in body
    assert "import " not in body
    for hook in ('"install"', '"activate"', '"fetch"', '"message"'):
        assert hook in body
    # …and the payload the body reads is the one the server just generated.
    assert "self.skipWaiting()" in body
    assert "self.clients.claim()" in body


def test_the_routing_table_bypasses_the_api_and_the_socket():
    """A cached action or projection would turn a network failure into a stale success —
    the one failure mode an offline app cannot afford (the M3.3 queue replays through it)."""
    body = _worker(_app())

    assert "/basis/api/" in body
    assert "BYPASS.test(url.pathname)" in body


def test_the_shell_is_precached_and_the_runtime_is_not():
    config = _config(_app())

    precache = config["precache"]
    assert all(url.startswith("/") for url in precache)
    # The framework's client modules, its shared package and the plugin's own code are the
    # shell; the app's start page is added so a cold offline start lands on the app.
    assert "/basis/client/component.js" in precache
    assert "/basis/client/entrypoint.py" in precache
    assert "/basis/plugins/mobile/store.py" in precache
    assert "/" in precache  # the default start_url
    # …and the 10–30 MB runtime is not: it warms into the immutable bucket by being
    # fetched, which the first visit does anyway.
    assert not [url for url in precache if url.startswith("/pyscript/")]


def test_the_apps_own_component_files_are_part_of_the_shell(tmp_path):
    """A mount's files are the URLs the runtime fetches (``mount + relpath``); the
    manifest only carries a label for them, so the precache has to resolve it."""
    components = tmp_path / "shell_components"
    components.mkdir()
    (components / "widget.py").write_text("class Widget:\n    pass\n")

    app = _app()
    app.include_components_dir(
        "/shell_components", str(components), name="shell_components"
    )

    assert "/shell_components/widget.py" in _config(app)["precache"]


def test_the_registration_module_is_precached():
    """The URL the client registers *from* cannot be fetched on the visit that needs it.

    The shell is installed before the page is interactive, and a cold offline start has to
    register and warm from cache — so this URL is precached even though no VFS inventory
    lists it (it is JavaScript, not a Python module the runtime imports).
    """
    assert REGISTER_URL in _config(_app())["precache"]


def test_the_start_pages_boot_plan_is_precached():
    """Without its plan the cached document cannot start Python at all.

    ``/pyscript.json?url=…`` is the boot plan (entrypoint, bootstrap), and PyScript aborts
    the boot when that fetch fails — so a shell that precaches the start page but not its
    plan renders markup and no interpreter. It is derived with the framework's own rule, so
    it matches the URL the page's ``config`` attribute carries.
    """
    precache = _config(_app(start_url="/demo"))["precache"]

    assert "/pyscript.json?url=/demo" in precache
    # The page's own declaration is the source, so the two cannot drift.
    page = TestClient(_app(start_url="/demo")).get("/demo").text
    assert 'config="/pyscript.json?url=/demo"' in page


def test_an_app_whose_start_url_is_not_a_page_has_no_boot_plan_to_precache():
    """A mistyped start_url (or a hand-rolled route) has no plan: nothing to invent."""
    app = _app(start_url="/nowhere")
    assert not [url for url in _config(app)["precache"] if url.startswith("/pyscript.json")]


def test_a_discovered_stores_directory_is_served_and_versioned(tmp_path):
    """An app with conventional dirs boots, and its ``stores/`` files are part of the shell.

    The discovery registry is keyed by name; walking it as a list of mounts is a 500 on the
    worker route, which is exactly what the browser lane found the hard way.
    """
    package = tmp_path / "src" / "discovered_app"
    (package / "components").mkdir(parents=True)
    (package / "stores").mkdir()
    (package / "__init__.py").write_text("")
    (package / "components" / "__init__.py").write_text("")
    (package / "stores" / "__init__.py").write_text("")
    (package / "stores" / "pwa.py").write_text(
        "from basis.plugins.mobile import PwaStore\npwa = PwaStore('pwa', title='App')\n"
    )

    PwaStore("pwa", title="App")
    app = Basis()
    app._app_dir = package
    app._auto_discover_dirs()
    app.bootstrap()

    config = _config(app)

    assert "/discovered_app/stores/pwa.py" in config["precache"]
    assert re.fullmatch(r"[0-9a-f]{12}", config["version"])


def test_the_precache_follows_the_declared_start_url():
    app = _app(start_url="/demo")
    assert "/demo" in _config(app)["precache"]


def test_the_version_changes_when_a_served_script_changes(tmp_path):
    """JavaScript the client boots on counts as shell code.

    ``basis/client/component.js`` and the plugin's ``register.js`` are cached at install;
    a stale copy in the shell cache would only be replaced when the version moves, so a
    changed ``.js`` file has to move it.
    """
    import os
    import time

    mount = tmp_path / "script_components"
    mount.mkdir()
    (mount / "widget.py").write_text("class Widget:\n    pass\n")
    script = mount / "widget.js"
    script.write_text("export const one = 1;\n")

    PwaStore("pwa", title="Myapp")
    app = Basis()
    app.bootstrap()
    app.include_components_dir("/script_components", str(mount), name="script_components")
    before = _config(app)["version"]

    time.sleep(0.01)
    script.write_text("export const one = 2;\n")
    os.utime(script, None)

    assert _config(app)["version"] != before


def test_the_same_app_gets_the_same_version():
    """A version that moved on every request would reinstall the shell on every navigation."""
    app = _app()
    client = TestClient(app)

    first = client.get(SERVICE_WORKER_URL).text
    second = client.get(SERVICE_WORKER_URL).text

    assert first == second


def test_the_version_changes_when_a_served_file_changes(tmp_path):
    import os
    import time

    from basis.server.app import Basis as BasisApp

    component_dir = tmp_path / "worker_components"
    component_dir.mkdir()
    module = component_dir / "widget.py"
    module.write_text("class Widget:\n    pass\n")

    PwaStore("pwa", title="Myapp")
    app = BasisApp()
    app.bootstrap()
    app.include_components_dir("/worker_components", str(component_dir), name="worker_components")
    app.include_page(
        "/demo",
        page_cls=type(
            "WorkerTmpPage",
            (Page,),
            {
                "title": "tmp",
                "root_component": type("WorkerTmpRoot", (Component,), {"template": "<div>x</div>"}),
            },
        ),
    )
    before = _config(app)["version"]

    # An edit (a changed mtime is what the digest reads) must produce a new shell.
    time.sleep(0.01)
    module.write_text("class Widget:\n    value = 1\n")
    os.utime(module, None)

    assert _config(app)["version"] != before


def test_the_version_changes_when_the_runtime_bundle_changes(monkeypatch):
    """A PyScript upgrade replaces the runtime under the shell's feet."""
    import basis.server.static as static

    app = _app()
    before = _config(app)["version"]

    monkeypatch.setattr(static, "offline_pyscript_url", lambda: "/pyscript/other")

    assert _config(app)["version"] != before


def test_the_version_is_short_and_deterministic():
    version = _config(_app())["version"]

    assert re.fullmatch(r"[0-9a-f]{12}", version)
