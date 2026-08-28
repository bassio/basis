"""
Tests for headless components — multi-file components where the ``.html`` (±
``.css``) exist but the ``.py`` logic file does not yet.

Covers (see HEADLESS-COMPONENTS-PLAN.md, Option D — static-handler synthetic):
* Detection: bare ``*.html`` at the mount root with no owning ``.py`` is promoted;
  an owned companion (same-stem ``.py``) is NOT headless.
* Identity: ``todo_list.html`` -> class ``TodoList``, tag ``todo-list``, module
  ``<mount_pkg>.todo_list`` (the module a future ``.py`` would use).
* Server registration: a real reactive Component subclass lands in ``_registry``.
* Serving: the synthetic module is served in-memory by the static handler (text
  in ``.py`` mode, compiled bytecode in pyc mode) while no real file exists.
* Collision guard: a real component with the same tag is never shadowed.
* Graduation: adding ``todo_list.py`` swaps the manifest entry (same URL/module)
  and headless promotion stops.
* SSR: a page whose root renders ``<todo-list>`` mounts the headless class and
  renders its template + bindings; ``#basis-headless-imports`` is emitted.
* HMR: headless ``.html``/``.css`` map to the synthetic module; edits regenerate
  the served source.
* Pruning: removing the mount removes the synthetic entries.
"""
import marshal
import sys

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.server.headless import headless_identity
from basis.shared.base_component import BaseComponent
from basis.shared.component import Component


@pytest.fixture(autouse=True)
def _clean_registries():
    """Reset global registries + class-level mount lists per test."""
    before = set(BaseComponent._registry)
    Basis._component_routes = []
    Basis._component_dirs = []
    yield
    for tag in set(BaseComponent._registry) - before:
        del BaseComponent._registry[tag]
    Basis._component_routes = []
    Basis._component_dirs = []


def _write(dir_path, name, content):
    p = dir_path / name
    p.write_text(content, encoding="utf-8")
    return p


def _headless_dir(tmp_path):
    """components/ with one headless component (todo_list) + one real component."""
    comp = tmp_path / "components"
    comp.mkdir()
    _write(comp, "todo_list.html", '<div class="card"><h3>{title}</h3><p>hi</p></div>')
    _write(comp, "todo_list.css", ".card { border: 1px solid #ccc; }")
    # A real component with an owned .html companion — NOT headless.
    _write(comp, "status.py", "class Status:\n    pass\n")
    _write(comp, "status.html", "<div>status</div>")
    return comp


# ---------------------------------------------------------------------------
# Detection + identity + registration
# ---------------------------------------------------------------------------

def test_headless_detection_promotes_class(tmp_path):
    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")

    # Synthetic module source generated + advertised.
    assert "todo_list.py" in app.vfs.synthetic_files
    src = app.vfs.synthetic_files["todo_list.py"]
    assert "class TodoList(Component):" in src
    assert "__tag__ = 'todo-list'" in src
    assert "<h3>{title}</h3>" in src
    assert ".card { border: 1px solid #ccc; }" in src

    assert "components.todo_list" in app.vfs.client_modules
    assert app.vfs.headless_modules == ["components.todo_list"]

    # Manifest maps the synthetic module where a future real .py would live.
    assert "{COMPONENTS_DIR_1}/todo_list.py" in app.vfs.files
    assert app.vfs.files["{COMPONENTS_DIR_1}/todo_list.py"] == "./components/todo_list.py"
    # Real .html/.css listed for transparency (companion-style).
    assert app.vfs.files["{COMPONENTS_DIR_1}/todo_list.html"] == "./components/todo_list.html"

    # Server-side class registered + reactive.
    cls = BaseComponent._registry["todo-list"]
    assert cls is not None
    assert cls.__name__ == "TodoList"
    assert getattr(cls, "__headless__", False) is True
    assert cls.__module__ == "components.todo_list"
    assert "<h3>{title}</h3>" in cls._get_template_string()
    assert ".card { border: 1px solid #ccc; }" in cls._get_style_string()


def test_headless_identity():
    assert headless_identity("myapp.components", "rating_stars") == (
        "RatingStars",
        "rating-stars",
        "myapp.components.rating_stars",
    )
    assert headless_identity("myapp.components", "todo_list") == (
        "TodoList",
        "todo-list",
        "myapp.components.todo_list",
    )


def test_owned_html_is_not_headless(tmp_path):
    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")

    # status.html is owned by status.py — NOT promoted.
    assert "components.status" not in app.vfs.headless_modules
    assert "status.py" not in app.vfs.synthetic_files
    # Only the one headless module was promoted.
    assert app.vfs.headless_modules == ["components.todo_list"]


def test_headless_collision_guard_never_shadows_real(tmp_path):
    class RealTodoList(Component):
        """<div>real</div>"""
        __tag__ = "todo-list"

    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")

    # The real component owns the tag; promotion was skipped (no synthetic file).
    assert BaseComponent._registry["todo-list"] is RealTodoList
    assert app.vfs.synthetic_files == {}
    assert app.vfs.headless_modules == []


# ---------------------------------------------------------------------------
# Serving (Option D — static-handler synthetic)
# ---------------------------------------------------------------------------

def test_headless_serving_via_static_handler(tmp_path):
    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")

    with TestClient(app) as client:
        # Synthetic module served in-memory (no file exists on disk).
        r = client.get("/components/todo_list.py")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/x-python")
        assert "class TodoList(Component):" in r.text
        # Real asset still served from disk.
        assert client.get("/components/todo_list.html").status_code == 200


def test_headless_serving_pyc_mode(tmp_path):
    comp = _headless_dir(tmp_path)
    app = Basis(pyc_mode=True)
    app.include_components_dir("/components", str(comp), name="components")

    # pyc-mode manifest names the synthetic module with .pyc.
    assert "{COMPONENTS_DIR_1}/todo_list.pyc" in app.vfs.files
    assert app.vfs.files["{COMPONENTS_DIR_1}/todo_list.pyc"] == "./components/todo_list.pyc"

    with TestClient(app) as client:
        r = client.get("/components/todo_list.pyc")
        assert r.status_code == 200
        assert r.headers["content-type"] in (
            "application/x-python-code",
            "application/x-bytecode.python",
        )
        code_obj = marshal.loads(r.content[16:])
        namespace = {}
        exec(code_obj, namespace)
        assert "TodoList" in namespace
        assert namespace["TodoList"].__tag__ == "todo-list"
        assert "<h3>{title}</h3>" in namespace["TodoList"].template


# ---------------------------------------------------------------------------
# Graduation — adding the .py swaps the manifest entry, promotion stops
# ---------------------------------------------------------------------------

def test_headless_graduation_swaps_manifest_entry(tmp_path):
    # Headless app.
    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")
    headless_key = "{COMPONENTS_DIR_1}/todo_list.py"
    assert app.vfs.files.get(headless_key) == "./components/todo_list.py"
    assert "components.todo_list" in app.vfs.headless_modules

    # Graduated app: the real .py now exists (same mount-relative URL/module).
    comp2 = tmp_path / "graduated"
    comp2.mkdir()
    _write(comp2, "todo_list.py", (
        "from basis.shared.component import Component\n\n"
        "class TodoList(Component):\n"
        "    __tag__ = 'todo-list'\n"
        "    \"\"\"<div>real now</div>\"\"\"\n"
    ))
    _write(comp2, "todo_list.html", '<div class="card"><h3>{title}</h3><p>hi</p></div>')
    _write(comp2, "todo_list.css", ".card { border: 1px solid #ccc; }")

    app2 = Basis()
    app2.include_components_dir("/components", str(comp2), name="components")

    # Not headless anymore.
    assert app2.vfs.synthetic_files == {}
    assert app2.vfs.headless_modules == []
    # Same module name is served by the real file at the SAME manifest URL.
    assert "components.todo_list" in app2.vfs.client_modules
    assert app2.vfs.files.get(headless_key) == "./components/todo_list.py"


# ---------------------------------------------------------------------------
# SSR end-to-end
# ---------------------------------------------------------------------------

def test_headless_ssr_renders_reactive_child(tmp_path):
    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")

    @app.page
    class Root(Component):
        """<div><todo-list title="Hello"></todo-list></div>"""

    with TestClient(app) as client:
        r = client.get("/")
        assert r.status_code == 200
        # The headless component's template rendered (binding resolved; the
        # <h3> also carries hydration-marker attributes).
        assert "Hello</h3>" in r.text
        # The shell points PyScript at the page-aware manifest.
        assert 'config="/pyscript.json?url=/"' in r.text
        # The manifest pre-imports the headless module (app-global bootstrap).
        manifest = client.get("/pyscript.json?url=/")
        assert manifest.status_code == 200
        payload = manifest.json()
        assert payload["basis"]["bootstrap"]["headless_modules"] == [
            "components.todo_list"
        ]


# ---------------------------------------------------------------------------
# HMR + regeneration + pruning
# ---------------------------------------------------------------------------

def test_headless_hmr_file_map(tmp_path):
    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")

    file_map = app._build_hmr_file_map()
    html_meta = file_map[str(comp / "todo_list.html")]
    css_meta = file_map[str(comp / "todo_list.css")]
    assert html_meta["module"] == "components.todo_list"
    assert css_meta["module"] == "components.todo_list"
    assert html_meta["ext"] == "html"
    assert css_meta["ext"] == "css"


def test_headless_regenerate_source_after_edit(tmp_path):
    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")

    _write(comp, "todo_list.html", '<div class="card"><h3>{title}</h3><p>edited</p></div>')
    assert app.vfs.regenerate_headless_source("/components", "todo_list.py") is True

    # Served synthetic source is fresh again (hard-refresh path).
    assert "<p>edited</p>" in app.vfs.synthetic_files["todo_list.py"]
    with TestClient(app) as client:
        r = client.get("/components/todo_list.py")
        assert "<p>edited</p>" in r.text


def test_headless_removal_prunes_synthetic(tmp_path):
    comp = _headless_dir(tmp_path)
    app = Basis()
    app.include_components_dir("/components", str(comp), name="components")
    assert "components.todo_list" in app.vfs.client_modules

    removed = app.vfs.remove_component_route("/components")
    assert removed is True
    assert app.vfs.synthetic_files == {}
    assert app.vfs.synthetic_modules == {}
    assert app.vfs.headless_modules == []
    assert "components.todo_list" not in app.vfs.client_modules
    assert not any("todo_list" in k for k in app.vfs.files)
