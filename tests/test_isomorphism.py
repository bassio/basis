"""Isomorphism guard — client-import safety (the fastapi gotcha).

The client (PyScript/Pyodide) imports framework modules from the VFS with no
``fastapi`` and with ``basis`` served as a namespace package (the server
``basis/__init__.py`` never runs). A plugin module that imports fastapi (or any
server-only dependency) at module scope breaks every CSR store/component import
("No module named 'fastapi'") — a regression the theme plugin hit in P3.

Two guards:

1. ``Request`` is shimmed on ``basis.shared.plugin`` (fastapi.Request on the
   server, an inert placeholder on the client), so plugin route handlers can
   annotate ``request: Request`` without importing fastapi. Verified in a
   subprocess (isolated ``sys.modules``) with the client environment simulated.
2. A source scan asserts no client-reachable module has an *unguarded*
   top-level ``from fastapi`` / ``import fastapi`` (col-0, outside a ``try``).
"""

import subprocess
import sys
from pathlib import Path

from basis import __file__ as _basis_init

#: Client-reachable framework packages (served to PyScript via the VFS).
_CLIENT_PACKAGES = ("plugins", "shared", "client")


def _client_dir() -> Path:
    # The package dir is the parent of basis/__init__.py. (Importing `basis`
    # here is fine — this test file runs server-side.)
    return Path(_basis_init).parent


def _client_module_files():
    root = _client_dir()
    for pkg in _CLIENT_PACKAGES:
        for path in sorted((root / pkg).rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            yield path


# --- 1. the Request shim is client-safe ------------------------------------

_CLIENT_SHIM_SIM = r"""
import importlib.util, sys, types
from pathlib import Path
sys.modules["fastapi"] = None                       # browser has no fastapi
sys.modules["pyscript"] = types.ModuleType("pyscript")  # flips IS_CLIENT
src = Path(importlib.util.find_spec("basis").submodule_search_locations[0])
def stub(name, path):
    m = types.ModuleType(name); m.__path__ = [str(path)]; sys.modules[name] = m
stub("basis", src)                      # namespace pkg — server __init__ never runs
stub("basis.shared", src / "shared")
stub("basis.client", src / "client")
import basis.shared.plugin
from basis.shared.plugin import Request
assert Request is object, "client Request shim should be object"
print("shim OK")
"""

_CLIENT_PAGE_SHIM_SIM = r"""
import importlib.util, sys, types
from pathlib import Path
sys.modules["pyscript"] = types.ModuleType("pyscript")
src = Path(importlib.util.find_spec("basis").submodule_search_locations[0])
def package(name, path):
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module
package("basis", src)
package("basis.shared", src / "shared")
package("basis.client", src / "client")
client_component = types.ModuleType("basis.client.component")
client_component.Component = type("Component", (), {})
sys.modules["basis.client.component"] = client_component
page = types.ModuleType("basis.shared.page")
class StaticPage:
    hydrates = False
    root_component = None
    stores = []
class Page(StaticPage):
    hydrates = True
def synthesized_page_base(component_cls, page_cls=None):
    if isinstance(component_cls, type) and issubclass(component_cls, StaticPage):
        raise TypeError("Page is not a root component")
    base = page_cls or Page
    if base.root_component is not None or base.stores:
        raise ValueError("complete page")
    if not base.hydrates:
        raise ValueError("no client")
    return base
def refuse_static_render_mode(page_cls, render_mode):
    if render_mode is not None and not page_cls.hydrates:
        raise ValueError("StaticPage")
page.StaticPage = StaticPage
page.Page = Page
page._synthesized_page_base = synthesized_page_base
page.refuse_static_render_mode = refuse_static_render_mode
sys.modules["basis.shared.page"] = page
base_component = types.ModuleType("basis.shared.base_component")
base_component.include_store = lambda value: value
base_component.include_model = lambda value: value
sys.modules["basis.shared.base_component"] = base_component
styling = types.ModuleType("basis.shared.styling")
styling.scoped = lambda value: value
styling.extra_style = lambda value: value
sys.modules["basis.shared.styling"] = styling

from basis.shared.component import Basis, Component

class Root(Component):
    pass

app = Basis()
decorated = app.page(Root, title="Client title")
assert decorated is Root
assert vars(Root)["_synthesized_page_args"] == {
    "page_cls": None,
    "title": "Client title",
    "pyscript_src": "https://pyscript.net/releases/2026.3.1",
}

class FactoryRoot(Component):
    pass
assert app.page(
    path="/factory",
    title="Factory",
    pyscript_src="/pyscript",
    render_mode="csr",
    name="factory",
)(FactoryRoot) is FactoryRoot
assert vars(FactoryRoot)["_synthesized_page_args"] == {
    "page_cls": None,
    "title": "Factory",
    "pyscript_src": "/pyscript",
}

class ChildRoot(FactoryRoot):
    pass
assert "_synthesized_page_args" not in vars(ChildRoot)

class ServedRoot(Component):
    pass
assert app.serve("/nested")(ServedRoot) is ServedRoot
assert vars(ServedRoot)["_synthesized_page_args"]["pyscript_src"].startswith("https://")

class InheritedSourceRoot(Component):
    pass
app.page(pyscript_src=None)(InheritedSourceRoot)
assert vars(InheritedSourceRoot)["_synthesized_page_args"]["pyscript_src"] is None

class FullPage(Page):
    pass
assert app.serve("/full")(FullPage) is FullPage
assert app.include_page("/full", page_cls=FullPage) is FullPage
assert app.include_page("/decorated")(FullPage) is FullPage
assert "_synthesized_page_args" not in vars(FullPage)

try:
    app.page(FullPage)
except TypeError:
    pass
else:
    raise AssertionError("app.page must reject a Page subclass")

try:
    app.page(Root, stores=["items"])
except TypeError:
    pass
else:
    raise AssertionError("client app.page must reject stores")
print("page shim OK")
"""


def test_request_shim_is_client_safe():
    result = subprocess.run(
        [sys.executable, "-c", _CLIENT_SHIM_SIM], capture_output=True, text=True
    )
    assert result.returncode == 0, f"client shim sim failed:\n{result.stdout}\n{result.stderr}"
    assert "shim OK" in result.stdout


def test_client_page_shim_annotates_the_root_class():
    result = subprocess.run(
        [sys.executable, "-c", _CLIENT_PAGE_SHIM_SIM],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"client page shim sim failed:\n{result.stdout}\n{result.stderr}"
    )
    assert "page shim OK" in result.stdout


# --- 2. no unguarded top-level fastapi in client-reachable modules ---------

def _unguarded_fastapi_imports(path: Path) -> list[str]:
    """Col-0 ``from fastapi``/``import fastapi`` lines not inside a ``try``.

    Guarded (``try: ... except ImportError``) and indented (lazy, inside a
    function) imports are fine — the danger is a bare module-scope import.
    """
    problems = []
    in_try = False
    for i, line in enumerate(path.read_text().splitlines(), 1):
        if not line.strip():
            continue
        if line == "try:":
            in_try = True
            continue
        if line.startswith("except") and not line.startswith(" "):
            in_try = False
            continue
        stripped = line.strip()
        if stripped.startswith(("from fastapi", "import fastapi")):
            if not line.startswith(" "):  # col 0
                if not in_try:
                    problems.append(f"  line {i}: {stripped}")
    return problems


def test_no_unguarded_fastapi_in_client_modules():
    offenders = {}
    for path in _client_module_files():
        problems = _unguarded_fastapi_imports(path)
        if problems:
            rel = path.relative_to(_client_dir())
            offenders[str(rel)] = problems
    assert not offenders, (
        "Unguarded top-level fastapi import(s) in client-reachable module(s) — "
        "the client has no fastapi and this breaks every CSR import:\n"
        + "\n".join(f"{k}:\n" + "\n".join(v) for k, v in offenders.items())
    )

