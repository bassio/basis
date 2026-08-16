"""
Tests for client-side HMR wiring (ROADMAP.md Critical #2).

Covers:
  * ``BASIS_HMR`` env var -> in-process file watcher enabled by default
  * the ``/ws/hmr`` WebSocket endpoint (single, stable registration)
  * the file watcher broadcasting an ``hmr`` message on component changes,
    including the authoritative client import ``module`` name for ``.py`` files
  * the module-name derivation map (incl. ``__pycache__`` exclusion)
  * the client's file -> component-class heuristic
"""
import os
import time

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.base_component import BaseComponent
from basis.shared.hmr import HMRClient


@pytest.fixture(autouse=True)
def _clean_registries():
    BaseComponent._registry.clear()
    BaseComponent._instance_registry.clear()
    BaseComponent._live_instances = type(BaseComponent._live_instances)()
    yield
    BaseComponent._registry.clear()
    BaseComponent._instance_registry.clear()


@pytest.fixture()
def components_dir(tmp_path):
    comp = tmp_path / "components"
    comp.mkdir()
    (comp / "my_comp.py").write_text("class MyComp:\n    pass\n")
    (comp / "my_comp.css").write_text("body { color: red; }\n")
    (comp / "my_comp.html").write_text("<div>Hello</div>\n")
    # Package-style component: titlebar/__init__.py + titlebar/titlebar.css/.html
    pkg = comp / "titlebar"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("class TitleBar:\n    pass\n")
    (pkg / "titlebar.css").write_text(".titlebar { height: 40px; }\n")
    (pkg / "titlebar.html").write_text("<div class='titlebar'></div>\n")
    sub = comp / "sub"
    sub.mkdir()
    (sub / "other.py").write_text("class Other:\n    pass\n")
    (sub / "__init__.py").write_text("")
    pycache = comp / "__pycache__"
    pycache.mkdir()
    (pycache / "my_comp.cpython-314.pyc").write_bytes(b"fake")
    return comp


def _make_app(components_dir):
    app = Basis()
    app.include_components_dir("/components/", str(components_dir), name="app_components")
    return app


# ---------------------------------------------------------------------------
# Watcher enablement
# ---------------------------------------------------------------------------

def test_hmr_watcher_disabled_by_default(components_dir, monkeypatch):
    monkeypatch.delenv("BASIS_HMR", raising=False)
    app = _make_app(components_dir)
    assert app._start_hmr_watcher is False


def test_hmr_watcher_enabled_via_env(components_dir, monkeypatch):
    monkeypatch.setenv("BASIS_HMR", "1")
    app = _make_app(components_dir)
    assert app._start_hmr_watcher is True


# ---------------------------------------------------------------------------
# Module-name file map
# ---------------------------------------------------------------------------

def test_hmr_file_map_module_names(components_dir):
    app = _make_app(components_dir)
    file_map = app._build_hmr_file_map()

    py_meta = file_map[str(components_dir / "my_comp.py")]
    assert py_meta["ext"] == "py"
    assert py_meta["module"] == "components.my_comp"

    nested_meta = file_map[str(components_dir / "sub" / "other.py")]
    assert nested_meta["module"] == "components.sub.other"

    init_meta = file_map[str(components_dir / "sub" / "__init__.py")]
    assert init_meta["module"] == "components.sub"

    css_meta = file_map[str(components_dir / "my_comp.css")]
    assert css_meta["ext"] == "css"
    assert css_meta["module"] == "components.my_comp"

    pkg_css = file_map[str(components_dir / "titlebar" / "titlebar.css")]
    assert pkg_css["module"] == "components.titlebar"
    pkg_html = file_map[str(components_dir / "titlebar" / "titlebar.html")]
    assert pkg_html["module"] == "components.titlebar"


def test_hmr_file_map_excludes_pycache(components_dir):
    app = _make_app(components_dir)
    file_map = app._build_hmr_file_map()
    assert not any("__pycache__" in key for key in file_map)
    assert not any(v.get("ext") == "pyc" for v in file_map.values())


# ---------------------------------------------------------------------------
# WebSocket endpoint + live broadcast
# ---------------------------------------------------------------------------

def test_hmr_ws_endpoint_accepts_connection(components_dir, monkeypatch):
    monkeypatch.setenv("BASIS_HMR", "1")
    app = _make_app(components_dir)
    with TestClient(app) as client:
        with client.websocket_connect("/ws/hmr") as ws:
            # Connection accepted + alive
            assert ws is not None


def _run_watcher_until_broadcast(app, target, new_content):
    """
    Run the watcher with a monkeypatched broadcast, change ``target`` after the
    initial scan records a baseline, and return the first broadcast message.
    """
    import asyncio

    async def scenario():
        received = []

        async def fake_broadcast(message):
            received.append(message)

        app.hmr_manager.broadcast = fake_broadcast
        task = asyncio.create_task(app._start_file_watcher())

        try:
            # Let the first scan record the baseline mtimes.
            await asyncio.sleep(0.7)

            target.write_text(new_content)
            future = time.time() + 5
            os.utime(target, (future, future))

            deadline = time.time() + 5
            while not received and time.time() < deadline:
                await asyncio.sleep(0.1)
            return received
        finally:
            task.cancel()

    return asyncio.run(scenario())


def test_hmr_watcher_broadcasts_css_change_with_module(components_dir):
    app = _make_app(components_dir)
    target = components_dir / "my_comp.css"
    received = _run_watcher_until_broadcast(app, target, "body { color: blue; }\n")

    assert received, "watcher never broadcast the CSS change"
    msg = received[0]
    assert msg["type"] == "hmr"
    assert msg["file"] == "my_comp.css"
    assert msg["ext"] == "css"
    assert "blue" in msg["content"]
    # The companion module owning this css file is included (flat-file convention)
    assert msg["module"] == "components.my_comp"


def test_hmr_watcher_broadcasts_package_css_with_module(components_dir):
    """Package-style companion css (titlebar/titlebar.css) maps to its package module."""
    app = _make_app(components_dir)
    target = components_dir / "titlebar" / "titlebar.css"
    received = _run_watcher_until_broadcast(app, target, ".titlebar { height: 80px; }\n")

    assert received, "watcher never broadcast the package CSS change"
    msg = received[0]
    assert msg["type"] == "hmr"
    assert msg["file"] == "titlebar/titlebar.css"
    assert msg["ext"] == "css"
    assert msg["module"] == "components.titlebar"
    assert "80px" in msg["content"]


def test_hmr_watcher_broadcasts_py_change_with_module(components_dir):
    app = _make_app(components_dir)
    target = components_dir / "my_comp.py"
    received = _run_watcher_until_broadcast(
        app, target, "class MyComp:\n    def ping(self):\n        return 'pong'\n"
    )

    assert received, "watcher never broadcast the .py change"
    msg = received[0]
    assert msg["type"] == "hmr"
    assert msg["ext"] == "py"
    assert msg["module"] == "components.my_comp"
    assert "pong" in msg["content"]


# ---------------------------------------------------------------------------
# Client-side pure logic (no PyScript needed on the server)
# ---------------------------------------------------------------------------

class FooBar:
    __tag__ = "foo-bar"


class Plain:
    __tag__ = "Plain"


def test_hmr_find_component_class_heuristic():
    BaseComponent._registry["foo-bar"] = FooBar
    BaseComponent._registry["Plain"] = Plain

    client = HMRClient.__new__(HMRClient)

    # snake_case file -> PascalCase class name
    assert client._find_component_class("foo_bar.css") is FooBar
    # kebab tag variant
    assert client._find_component_class("foo-bar.html") is FooBar
    # flat class name
    assert client._find_component_class("Plain.py") is Plain
    # explicit component_class wins
    assert client._find_component_class("whatever.css", component_class="FooBar") is FooBar
    # no match -> None
    assert client._find_component_class("nope.css") is None


def test_hmr_find_component_class_by_module():
    """A css/html file is matched by its authoritative module, not the filename."""
    # TitleBar lives in module ``pkg.components.titlebar`` but the css stem is
    # ``titlebar`` -> the filename heuristic would produce ``Titlebar`` (no match).
    TitleBar = type("TitleBar", (), {"__module__": "pkg.components.titlebar"})
    BaseComponent._registry["title-bar"] = TitleBar

    client = HMRClient.__new__(HMRClient)

    assert client._find_component_class(
        "titlebar/titlebar.css", module="pkg.components.titlebar"
    ) is TitleBar
    assert client._find_component_class(
        "titlebar/titlebar.html", module="pkg.components.titlebar"
    ) is TitleBar
    # Without the module, the filename heuristic does NOT match TitleBar
    assert client._find_component_class("titlebar/titlebar.css") is None
