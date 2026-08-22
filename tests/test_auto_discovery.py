"""
Tests for conventional-directory auto-discovery + the isomorphism invariant.

The isomorphism principle: for every component file the client can import, its
PyScript VFS import name MUST equal the filesystem import name (what the server
and IDEs resolve). Auto-discovery enforces this by mounting ``components/`` and
``stores/`` at package-derived paths (the dir must be a real Python package —
an ``__init__.py``).

Covers:
* ``_resolve_canonical_package`` — regular packages resolve; namespace-only dirs → None.
* ``_discover_conventional_dirs`` / ``Basis._auto_discover_dirs`` — discovers and
  mounts ``components/`` + ``stores/`` at package-derived paths; skips non-packages.
* ``Basis._auto_import_stores`` — imports ``stores/`` modules (registering
  blueprints) and returns their dotted names.
* ``Store.all_names`` / ``Store.resolve``.
* ``Page.load`` name-list + default-to-all store resolution.
* ``@app.page`` isomorphism — a component inside a discovered dir gets NO legacy
  ``"/"`` mount and an isomorphic entry URL; a bare single-file app keeps it.
* The isomorphism guard warns on a non-isomorphic mount.
"""
import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.server.plugins import _resolve_canonical_package
from basis.server.bootstrap import _discover_conventional_dirs
from basis.shared.store import Store
from basis.shared.component import Component
from basis.shared.page import Page


@pytest.fixture(autouse=True)
def _clean_registries():
    Store._registry.clear()
    Store._store_blueprints.clear()
    # _component_routes is a CLASS-level list shared by every Basis instance;
    # reset it so mounts from one test don't leak into another.
    Basis._component_routes = []
    Basis._component_dirs = []
    yield
    Store._registry.clear()
    Store._store_blueprints.clear()
    Basis._component_routes = []
    Basis._component_dirs = []


# ---------------------------------------------------------------------------
# _resolve_canonical_package
# ---------------------------------------------------------------------------

def test_resolve_canonical_package_regular_package(tmp_path):
    pkg = tmp_path / "src" / "myapp"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "plugins").mkdir(exist_ok=True)
    (pkg / "components").mkdir(exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "plugins" / "__init__.py").write_text("")
    (pkg / "components" / "__init__.py").write_text("")

    assert _resolve_canonical_package(pkg / "plugins") == "myapp.plugins"
    assert _resolve_canonical_package(pkg / "components") == "myapp.components"


def test_resolve_canonical_package_namespace_only_returns_none(tmp_path):
    # A namespace subdir with NO __init__.py is intentionally not resolved —
    # auto-discovery requires real packages so the VFS namespace can match the
    # filesystem (and stay reliable for IDEs).
    pkg = tmp_path / "src" / "myapp"
    (pkg / "components").mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")

    assert _resolve_canonical_package(pkg / "components") is None


# ---------------------------------------------------------------------------
# _discover_conventional_dirs / _auto_discover_dirs
# ---------------------------------------------------------------------------

def _make_app_layout(tmp_path, package="myapp", with_stores=True):
    """Build src/<package>/{components,stores} as real packages."""
    src = tmp_path / "src"
    pkg = src / package
    (pkg / "components").mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "components" / "__init__.py").write_text("")
    (pkg / "components" / "foo.py").write_text("")
    if with_stores:
        (pkg / "stores").mkdir(exist_ok=True)
        (pkg / "stores" / "__init__.py").write_text("")
        (pkg / "stores" / "state.py").write_text(
            "from basis.shared.store import Store\n"
            "auto_store = Store('auto_discovered_store')\n"
        )
    return pkg


def test_discover_conventional_dirs_finds_packages(tmp_path):
    pkg = _make_app_layout(tmp_path)
    found = _discover_conventional_dirs(pkg)
    names = {f["name"] for f in found}
    assert names == {"components", "stores"}
    assert next(f for f in found if f["name"] == "components")["pkg"] == "myapp.components"
    assert next(f for f in found if f["name"] == "stores")["pkg"] == "myapp.stores"


def test_auto_discover_mounts_at_package_derived_paths(tmp_path):
    pkg = _make_app_layout(tmp_path)
    app = Basis()
    app._app_dir = pkg
    app._auto_discover_dirs()

    assert app._discovered_dirs["components"]["pkg"] == "myapp.components"
    assert app._discovered_dirs["stores"]["pkg"] == "myapp.stores"
    paths = [getattr(m, "path", None) for m in app._component_routes]
    assert "/myapp/components" in paths
    assert "/myapp/stores" in paths


def test_auto_discover_skips_non_package_dir(tmp_path):
    (tmp_path / "components").mkdir()
    (tmp_path / "components" / "foo.py").write_text("")

    app = Basis()
    app._app_dir = tmp_path
    app._auto_discover_dirs()

    assert "components" not in app._discovered_dirs
    assert "/components/" not in [getattr(m, "path", None) for m in app._component_routes]


def test_auto_discover_is_idempotent_against_explicit_mount(tmp_path):
    pkg = _make_app_layout(tmp_path)
    app = Basis()
    app._app_dir = pkg
    # Explicit mount at the SAME package-derived path — auto-discovery must not
    # add a duplicate.
    app.include_components_dir(
        "/myapp/components/", str(pkg / "components"), name="explicit"
    )
    app._auto_discover_dirs()

    paths = [getattr(m, "path", None) for m in app._component_routes]
    assert paths.count("/myapp/components") == 1


# ---------------------------------------------------------------------------
# _auto_import_stores
# ---------------------------------------------------------------------------

def test_auto_import_stores_imports_modules_and_registers_blueprints(tmp_path, monkeypatch):
    pkg = _make_app_layout(tmp_path)
    monkeypatch.syspath_prepend(str(pkg.parent))  # src/ on path

    app = Basis()
    app._app_dir = pkg
    app._auto_discover_dirs()
    modules = app._auto_import_stores()

    assert modules == ["myapp.stores.state"]
    assert "auto_discovered_store" in Store.all_names()
    assert Store._registry.get("auto_discovered_store") is not None


# ---------------------------------------------------------------------------
# Store.all_names / Store.resolve / Page.load
# ---------------------------------------------------------------------------

def test_store_all_names_and_resolve():
    class S(Store):
        def __init__(self, name, n=0):
            super().__init__(name)
            self.n = n

    S("res_store", n=5)
    assert "res_store" in Store.all_names()

    # After a per-request registry reset, resolve rebuilds the proper subclass
    # with constructor args from the persistent blueprint.
    Store._registry.clear()
    revived = Store.resolve("res_store")
    assert isinstance(revived, S)
    assert revived.n == 5


def test_page_load_resolves_name_list():
    class CStore(Store):
        def __init__(self, name):
            super().__init__(name)
            self.v = 1

    CStore("name_list_store")
    Store._registry.clear()

    class P(Page):
        stores = ["name_list_store"]

    P.load(ssr=True, request=None)
    store = Store._registry.get("name_list_store")
    assert isinstance(store, CStore)
    assert store.v == 1


def test_page_load_defaults_to_all_stores():
    class Dummy(Store):
        pass

    Dummy("dummy_all")
    Store._registry.clear()

    class P(Page):
        pass  # stores defaults to [] → "all auto-discovered"

    P.load(ssr=True, request=None)
    assert "dummy_all" in Store._registry


def test_page_load_rejects_instance_list():
    """Page.stores is a name-list — store *instances* are a loud error.

    The convention is module-scope instantiation (e.g. in a stores/ module)
    referenced by name, so a stray instance is a clear migration signal rather
    than a silent behaviour branch.
    """
    class InstStore(Store):
        def __init__(self, name, label="x"):
            super().__init__(name)
            self.label = label

    Store._registry.clear()

    class P(Page):
        stores = [InstStore("inst_list", label="kept")]

    with pytest.raises(TypeError, match="must be store names"):
        P.load(ssr=True, request=None)


# ---------------------------------------------------------------------------
# @app.page isomorphism
# ---------------------------------------------------------------------------

def test_page_decorator_covered_component_no_root_mount(tmp_path, monkeypatch):
    pkg = _make_app_layout(tmp_path, package="covapp", with_stores=False)
    (pkg / "components" / "hello.py").write_text(
        "from basis.shared.component import Component\n"
        "class Hello(Component):\n"
        "    \"\"\"<div>Hi</div>\"\"\"\n"
    )
    monkeypatch.syspath_prepend(str(pkg.parent))

    import covapp.components.hello as hello_mod

    app = Basis()
    app._app_dir = pkg
    app._auto_discover_dirs()

    # The component is inside the discovered components/ dir → covered.
    assert app.vfs.component_module_name(hello_mod.Hello) == "covapp.components.hello"

    app.page(hello_mod.Hello)

    paths = [getattr(m, "path", None) for m in app._component_routes]
    assert "/covapp/components" in paths
    # No legacy "/" (catch-all) mount was added.
    assert "" not in paths

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    # The isomorphic PyScript entry URL, not the bare "/hello.py".
    assert 'src="/covapp/components/hello.py"' in resp.text


def test_page_decorator_single_file_keeps_root_mount(tmp_path, monkeypatch):
    # A bare single-file component (not inside any discovered dir) keeps the
    # legacy "/" mount (isomorphic for a component at the app root).
    app = Basis()
    app._app_dir = tmp_path

    component_file = tmp_path / "hello.py"
    component_file.write_text(
        "from basis.shared.component import Component\n"
        "class Hello(Component):\n"
        "    \"\"\"<div>Hi</div>\"\"\"\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    import hello as hello_mod

    app.page(hello_mod.Hello)

    paths = [getattr(m, "path", None) for m in app._component_routes]
    assert "" in paths  # "/" mount present


# ---------------------------------------------------------------------------
# Isomorphism guard
# ---------------------------------------------------------------------------

def test_isomorphism_guard_warns_on_non_isomorphic_mount(tmp_path, monkeypatch, caplog):
    pkg = _make_app_layout(tmp_path, package="guardapp", with_stores=False)
    monkeypatch.syspath_prepend(str(pkg.parent))

    app = Basis()
    # Deliberately mount at a path that does NOT reproduce the package path.
    app.include_components_dir("/wrong/", str(pkg / "components"), name="wrong")

    with caplog.at_level("WARNING", logger="uvicorn.error"):
        app.vfs.log_warnings()

    assert any("Isomorphism violation" in r.getMessage() for r in caplog.records)
