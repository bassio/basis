import asyncio
import functools
import importlib.util
import inspect
import itertools
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from contextlib import asynccontextmanager
import sys
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from basis.server.static import BasisStaticFiles, BasisStaticFilesPyc
from basis.server.vfs import (
    companion_assets,
    mount_to_module_name,
    normalize_mount,
    vfs_relative_url,
)
from fastapi import FastAPI, Request
from basis.server.plugin import BasisPlugin
from fastapi.responses import JSONResponse, HTMLResponse

from basis.server.db import DBAppMixin
from basis.server.hmr import HMRManager, HMRMixin


ONLINE_PYSCRIPT = "https://pyscript.net/releases/2026.3.1"

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


def _synthesize_page(
    component_cls,
    *,
    page_cls=None,
    title=None,
    stores=None,
    entry_module=None,
    pyscript_src=None,
):
    """Build a synthesized Page subclass that carries ``component_cls`` as its root.

    Used by ``@app.page`` to turn a root
    Component into a page without the developer writing a ``Page`` subclass. The
    synthesized class is server-side shell config only; it is marked
    ``__synthesized__`` so the client (which boots from the component file) never
    tries to import it via ``#basis-entrypoint-imports``.

    Because of that client boot path, page-level ``stores`` cannot reach the
    browser here — a shell that declares its own ``root_component`` or ``stores``
    is a complete page and belongs in ``app.include_page`` instead.
    """
    from basis.shared.page import Page as PageBase

    base = page_cls or PageBase

    if getattr(base, "root_component", None) is not None or getattr(base, "stores", None):
        raise ValueError(
            f"{base.__name__} already declares root_component/stores — it's a complete "
            f"page. Register it with app.include_page(path, page_cls={base.__name__}) "
            f"instead of decorating a component with it."
        )

    derived = type(
        f"{component_cls.__name__}Page",
        (base,),
        {
            "__module__": component_cls.__module__,
            "root_component": component_cls,
            "title": title if title is not None else getattr(base, "title", "Basis App"),
            "stores": list(stores) if stores is not None else list(getattr(base, "stores", [])),
            "__synthesized__": True,
        },
    )
    if entry_module is not None:
        derived.entry_module = entry_module
    if pyscript_src is not None:
        derived.pyscript_src = pyscript_src
    return derived


@dataclass
class PluginRegistration:
    """App-side record of one plugin's registration.

    ``include_plugin`` fills the inverse of every registration site so
    ``remove_plugin`` / ``disable_plugin`` can unwind them. The plugin registry
    *store* (``$plugins``) is a reactive projection of these records.
    """
    plugin: "BasisPlugin"
    state: str = "enabled"
    added_routes: list = field(default_factory=list)
    component_mount: Any | None = None
    page_route: Any | None = None
    models: set = field(default_factory=set)
    region_items: list = field(default_factory=list)
    action_registry_entries: dict = field(default_factory=dict)
    disposed: bool = False


def _topo_sort_plugins(
    plugins: list["BasisPlugin"],
    registered_names: set[str] | None = None,
) -> list["BasisPlugin"]:
    """Return *plugins* in dependency order (dependencies first), by ``requires``.

    Raises ``ValueError`` naming the missing dependency (a required plugin that is
    neither in *plugins* nor already registered) or the plugins in a dependency
    cycle. Auto-discovery uses this so a discovered plugin is always registered
    after the plugins it requires.
    """
    by_name = {p.name: p for p in plugins}
    known = set(by_name) | set(registered_names or ())
    missing = sorted({r for p in plugins for r in p.requires if r not in known})
    if missing:
        detail = "; ".join(
            f"'{p.name}' requires {', '.join(p.requires)}"
            for p in plugins
            if p.requires
        )
        raise ValueError(
            f"Plugin dependency not satisfied: missing required plugin(s) {missing}. {detail}"
        )

    indeg = {p.name: 0 for p in plugins}
    required_by: dict[str, list[str]] = {}
    for p in plugins:
        for r in p.requires:
            if r in by_name:  # intra-set dependency (external deps are satisfied)
                indeg[p.name] += 1
                required_by.setdefault(r, []).append(p.name)

    queue = [p.name for p in plugins if indeg[p.name] == 0]
    order = []
    while queue:
        name = queue.pop()
        order.append(name)
        for dependent in required_by.get(name, []):
            indeg[dependent] -= 1
            if indeg[dependent] == 0:
                queue.append(dependent)

    if len(order) != len(plugins):
        cyclic = sorted(p.name for p in plugins if p.name not in order)
        raise ValueError(f"Plugin dependency cycle detected among: {cyclic}")

    return [by_name[n] for n in order]


def initialize_pyscript_registry(app: FastAPI):
    """
    Initializes the PyScript VFS and module registry on startup.
    Caches:
      - app.state.vfs_files: The file mapping dictionary for pyscript.json
      - app.state.client_modules: The list of modules available in the PyScript client VFS
      - app.state.vfs_to_server_module: The reverse mapping for RPC server action routing
    """
    pyc_mode = getattr(app, "pyc_mode", False)
    py_ext = ".pyc" if pyc_mode else ".py"

    files_dict = {}
    client_modules = []
    vfs_to_server_module = {}
    
    # add client side code (currently under /client)

    #for entrypoint .py files : do not convert these to .pyc
    files_dict["{DOMAIN}/basis/client/entrypoint.py"] = "./basis/client/entrypoint.py"

    client_py_files = [
        "component.py",
        "plugin.py",
        "actions.py",
        "errors.py",
        "errors_component.py",
    ]
    for f_name in client_py_files:
        stem = Path(f_name).stem
        target_name = stem + py_ext # py_ext depends on whether pyc mode is enabled or not
        files_dict[f"{{DOMAIN}}/basis/client/{target_name}"] = f"./basis/client/{target_name}"
    
    files_dict["{DOMAIN}/basis/client/component.js"] = "./basis/client/component.js"

    # add shared
    shared_py_files = [
        "expr.py",
        "loop.py",
        "reactive.py",
        "bindings.py",
        "base_component.py",
        "element.py",
        "component.py",
        "page.py",
        "store.py",
        "store_provider.py",
        "context.py",
        "hmr.py",
        "hydration.py",
        "errors.py",
        "actions.py",
        "plugin.py",
        "router.py",
        "db.py",
        "basis_await.py",
        "validation.py",
        "plugin_registry.py",
        "region.py",
    ]
    for f_name in shared_py_files:
        stem = Path(f_name).stem
        target_name = stem + py_ext
        files_dict[f"{{DOMAIN}}/basis/shared/{target_name}"] = f"./basis/shared/{target_name}"

    for i, m in enumerate(app._component_routes, 1):
        cdir_n_label = '{' + f'COMPONENTS_DIR_{i}' + '}'
        mount_path = m.path   # mount path
        c_dir = Path(m.app.directory).absolute()

        clean_mount = normalize_mount(mount_path)

        files_dict[cdir_n_label] = "{DOMAIN}" + clean_mount

        if not c_dir.exists():
            continue

        for f in itertools.chain(c_dir.glob("*.py"), c_dir.glob("**/*.py")):
            rel_py = f.relative_to(c_dir)
            # VFS file name carries the pyc extension in pyc mode
            rel_vfs = rel_py.with_name(f.stem + py_ext if pyc_mode else f.name)

            # component_file uses '/' as path separator in PyScript VFS
            component_file = cdir_n_label + "/" + rel_vfs.as_posix()
            component_file = component_file.replace("//", "/")

            # Server relative URL must always start with './' and use POSIX path separators
            files_dict[component_file] = vfs_relative_url(clean_mount, rel_vfs)

            # Translate file path to Python import path (isomorphic: VFS == filesystem)
            vfs_module_path = mount_to_module_name(clean_mount, rel_vfs)
            if vfs_module_path is None:
                continue

            if vfs_module_path not in client_modules:
                client_modules.append(vfs_module_path)

            for asset in companion_assets(f):
                if asset.exists():
                    rel_asset = rel_py.parent / asset.name
                    asset_file = cdir_n_label + "/" + rel_asset.as_posix()
                    asset_file = asset_file.replace("//", "/")

                    files_dict[asset_file] = vfs_relative_url(clean_mount, rel_asset)

            # Resolve server-side Python module path
            for sys_path in sorted(sys.path, key=len, reverse=True):
                if not sys_path:
                    continue
                sys_path_abs = Path(sys_path).absolute()
                if f.is_relative_to(sys_path_abs):
                    rel_to_sys = f.relative_to(sys_path_abs)
                    server_parts = list(rel_to_sys.parts)
                    if server_parts[-1] == "__init__.py":
                        server_parts.pop()
                    else:
                        server_parts[-1] = rel_to_sys.stem
                    
                    vfs_to_server_module[vfs_module_path] = ".".join(server_parts)
                    break

    # Isomorphism guard: every client VFS import name must equal the server
    # import name. The whole framework — SSR, the client VFS, server RPC and IDE
    # resolution — assumes the SAME namespace, so a mount path that diverges
    # from the filesystem package path silently breaks imports. Warn loudly so
    # it can never slip in by accident. (Only entries with a resolvable server
    # module are comparable; files outside any sys.path package are covered by
    # conventional-dir discovery.)
    for vfs_name, server_name in vfs_to_server_module.items():
        if vfs_name != server_name:
            logger.warning(
                f"⚠️  Isomorphism violation: VFS module '{vfs_name}' maps to "
                f"server module '{server_name}'. Component mount paths must "
                f"reproduce the filesystem package path so client VFS, server "
                f"and IDEs resolve the same import names."
            )

    app.state.vfs_files = files_dict
    app.state.client_modules = client_modules
    app.state.vfs_to_server_module = vfs_to_server_module


async def pyscript_json(request: Request):
    base_url = str(request.base_url).removesuffix("/")
    
    files_dict = {
        "{DOMAIN}": base_url
    }
    
    raw_files = getattr(request.app.state, "vfs_files", {})
    for k, v in raw_files.items():
        key = k.replace("{DOMAIN}", base_url)
        files_dict[key] = v
        
    client_modules = getattr(request.app.state, "client_modules", [])
    
    return JSONResponse({
        "files": files_dict,
        "interpreter": "pyscript/pyodide/pyodide.mjs",
        "client_modules": client_modules
    })


# ------------------------------------------------------------------
# Plugin auto-discovery
# ------------------------------------------------------------------

def discover_local_plugins(app_dir: Path, plugins_dir: str = "plugins") -> list["BasisPlugin"]:
    """
    Scan the ``plugins/`` directory for BasisPlugin instances.

    Convention: each Python file or package in the directory must expose a
    module-level variable named ``plugin`` that is a ``BasisPlugin`` instance.
    Files/dirs starting with ``_`` are skipped.  Results are sorted
    alphabetically by filename for deterministic ordering.
    """
    plugins = []
    plugins_path = app_dir / plugins_dir

    if not plugins_path.exists() or not plugins_path.is_dir():
        return plugins

    # Try to determine the canonical Python package path for the plugins dir.
    # E.g. if app_dir is .../src/jotter and plugins_dir is "plugins",
    # then the package path is "jotter.plugins" and a file heroes.py within
    # would be importable as "jotter.plugins.heroes".
    canonical_pkg = _resolve_canonical_package(plugins_path)

    for item in sorted(plugins_path.iterdir()):
        if item.name.startswith("_"):
            continue

        module_name = None
        if item.is_file() and item.suffix == ".py":
            module_name = item.stem
        elif item.is_dir() and (item / "__init__.py").exists():
            module_name = item.name

        if not module_name:
            continue

        try:
            # Determine the canonical import path (e.g. "jotter.plugins.heroes")
            if canonical_pkg:
                canonical_name = f"{canonical_pkg}.{module_name}"
            else:
                canonical_name = f"plugins.{module_name}"

            # If already imported under the canonical name, just grab the plugin
            if canonical_name in sys.modules:
                mod = sys.modules[canonical_name]
                plugin_obj = getattr(mod, "plugin", None)
                if isinstance(plugin_obj, BasisPlugin):
                    plugins.append(plugin_obj)
                    logger.info(f"\U0001f50c Discovered local plugin: {plugin_obj.name} ({module_name})")
                continue

            # Import using the canonical name if it's a proper package,
            # otherwise fall back to spec_from_file_location.
            if canonical_pkg:
                mod = importlib.import_module(canonical_name)
            else:
                module_file = item if item.is_file() else item / "__init__.py"
                submodule_search = [str(item)] if item.is_dir() else None
                spec = importlib.util.spec_from_file_location(
                    canonical_name,
                    module_file,
                    submodule_search_locations=submodule_search,
                )
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                sys.modules[canonical_name] = mod
                spec.loader.exec_module(mod)

            plugin_obj = getattr(mod, "plugin", None)
            if isinstance(plugin_obj, BasisPlugin):
                plugins.append(plugin_obj)
                logger.info(f"\U0001f50c Discovered local plugin: {plugin_obj.name} ({module_name})")
            else:
                logger.debug(
                    f"Skipping plugins/{module_name}: no 'plugin' BasisPlugin variable found"
                )
        except Exception as e:
            logger.warning(f"\u26a0\ufe0f  Failed to load plugin '{module_name}': {e}")

    return plugins


def _resolve_canonical_package(path: Path) -> str | None:
    """
    Walk up from *path* to find the top-level Python package and return
    the dotted package name.  Returns ``None`` if *path* is not inside a
    recognisable Python package tree.

    Example: /home/user/project/src/myapp/plugins → "myapp.plugins"

    Note: the conventional subdirectories (components/, stores/, plugins/)
    are expected to be *regular* packages (they carry an ``__init__.py``) so
    this stays simple and IDE resolution stays reliable. Namespace packages
    (no ``__init__.py``) are intentionally NOT resolved here — they return
    ``None`` and auto-discovery skips them with a warning.
    """
    parts = []
    current = path.resolve()
    while (current / "__init__.py").exists():
        parts.append(current.name)
        current = current.parent
    if not parts:
        return None
    parts.reverse()
    return ".".join(parts)


# ------------------------------------------------------------------
# Conventional directory auto-discovery (components/ stores/)
# ------------------------------------------------------------------

def _discover_conventional_dirs(
    app_dir: Path,
    components_dir: str = "components",
    stores_dir: str = "stores",
) -> list[dict]:
    """
    Find conventional subdirectories under *app_dir* (``components/``,
    ``stores/``) that exist as proper Python packages.

    Isomorphism invariant: the mount path for a discovered dir reproduces its
    package path, so the client VFS import name equals the filesystem import
    name (and what IDEs resolve). A conventional dir is only discovered if it
    is a real package (has an ``__init__.py``); otherwise it is skipped with a
    warning — silently inventing a VFS-only namespace would break IDE parity.
    """
    found = []
    for name, subdir in (("components", components_dir), ("stores", stores_dir)):
        path = app_dir / subdir
        if not path.is_dir():
            continue
        pkg = _resolve_canonical_package(path)
        if pkg is None:
            logger.warning(
                f"⚠️  Skipping '{subdir}/' auto-discovery: not a Python package. "
                f"Add an (even empty) '{subdir}/__init__.py' so the client VFS "
                f"namespace can match the filesystem import namespace."
            )
            continue
        found.append({"name": name, "subdir": subdir, "dir": path, "pkg": pkg})
    return found


def _component_entry_url(app, component_file: Path) -> str | None:
    """
    Return the URL of *component_file* under the first component mount that
    contains it. Used as the isomorphic PyScript entry URL for ``@app.page``
    when the component already lives inside a discovered component dir.
    """
    for m in app._component_routes:
        c_dir = Path(m.app.directory).absolute()
        if component_file.is_relative_to(c_dir):
            clean_mount = normalize_mount(m.path)
            rel = component_file.relative_to(c_dir).as_posix()
            return f"{clean_mount}/{rel}"
    return None


def discover_installed_plugins(
    allowlist: list[str] | None = None,
    blocklist: list[str] | None = None,
) -> list["BasisPlugin"]:
    """
    Discover plugins registered via Python ``entry_points`` under the
    ``basis.plugins`` group.

    Parameters
    ----------
    allowlist:
        If provided, only load plugins whose entry-point name is in this list.
    blocklist:
        If provided, skip plugins whose entry-point name is in this list.
    """
    from importlib.metadata import entry_points as _entry_points

    plugins = []
    try:
        eps = _entry_points(group="basis.plugins")
    except Exception:
        return plugins

    for ep in eps:
        if allowlist is not None and ep.name not in allowlist:
            logger.debug(f"\u23ed\ufe0f  Skipping installed plugin '{ep.name}' (not in allowlist)")
            continue
        if blocklist is not None and ep.name in blocklist:
            logger.debug(f"\u23ed\ufe0f  Skipping installed plugin '{ep.name}' (in blocklist)")
            continue

        try:
            plugin_obj = ep.load()
            if isinstance(plugin_obj, BasisPlugin):
                dist_name = getattr(ep.dist, "name", "unknown") if ep.dist else "unknown"
                plugins.append(plugin_obj)
                logger.info(
                    f"\U0001f4e6 Loaded installed plugin: {plugin_obj.name} (from {dist_name})"
                )
        except Exception as e:
            logger.warning(f"\u26a0\ufe0f  Failed to load installed plugin '{ep.name}': {e}")

    return plugins


class Basis(FastAPI, DBAppMixin, HMRMixin):
    
    _component_dirs = []
    _component_routes = []
    _global_stores = []

    def __init__(self, *args, plugins_dir: str = "plugins",
                 components_dir: str = "components",
                 stores_dir: str = "stores",
                 plugins: list[str] | bool | None = None,
                 exclude_plugins: list[str] | None = None,
                 pyc_mode: bool = False,
                 **kwargs):
        # Client-side HMR is enabled by default for dev via the BASIS_HMR env var
        # (set by ``basis dev --hmr``), or programmatically via run_with_hmr().
        self._start_hmr_watcher = os.environ.get("BASIS_HMR", "").lower() in ("1", "true", "yes")
        self._plugins_dir = plugins_dir
        # Conventional auto-discovered directory names (see _auto_discover_dirs).
        self._components_dir = components_dir
        self._stores_dir = stores_dir
        # plugins=True/None → auto-discover all; plugins=["a","b"] → allowlist;
        # plugins=False → disable installed-plugin discovery (local still works)
        self._plugins_config = plugins
        self._exclude_plugins = exclude_plugins or []
        self.pyc_mode = pyc_mode or os.environ.get("BASIS_PYC_MODE", "").lower() in ("1", "true", "yes")
        if not hasattr(self, "_plugins"):
            self._plugins = []
        # Revertible plugin registration records (teardown truth, keyed by name).
        self._plugin_registrations = {}
        # App-housed region registry (ROADMAP-SPATIAL.md): {region: [RegionContribution]}.
        # Durable, boot-populated; the $regions store is a reactive projection.
        self._regions = {}
        self._region_seq = 0
        # Set when a plugin was added/removed so the HMR watcher rebuilds its map.
        self._hmr_map_dirty = True
        # Cache for _plugin_importers() — warmed at lifespan startup (alongside
        # the client VFS manifest) and invalidated on any structural change.
        self._plugin_importers_cache = None
        # Populated by _auto_discover_dirs / _auto_import_stores.
        self._discovered_dirs = {}
        self._discovered_store_modules = []
        # Capture the app directory now (call stack has the user's module)
        self._app_dir = self._detect_app_directory()

        user_lifespan = kwargs.get("lifespan")
        
        @asynccontextmanager
        async def basis_lifespan(app):
            # Ensure bootstrap is called
            app.bootstrap()
            
            # Precompute PyScript VFS files and action mappings
            initialize_pyscript_registry(app)
            # Warm the plugin→importers cache at app load, alongside the VFS
            # manifest: the "is this plugin essential?" decision has exactly the
            # manifest's lifetime. Rebuilt wherever the manifest is rebuilt
            # (startup, plugin remove/enable); invalidated on mounts/plugins.
            app._plugin_importers()

            # Call plugin on_startup hooks
            for plugin in getattr(app, "_plugins", []):
                try:
                    await plugin.on_startup(app)
                except Exception as e:
                    logger.warning(f"\u26a0\ufe0f  Plugin '{plugin.name}' on_startup failed: {e}")
            
            watcher_task = None
            if app._start_hmr_watcher:
                watcher_task = asyncio.create_task(app._start_file_watcher())
                
            try:
                if user_lifespan:
                    async with user_lifespan(app) as maybe_state:
                        yield maybe_state
                else:
                    yield
            finally:
                # Call plugin on_shutdown hooks (reverse order)
                for plugin in reversed(getattr(app, "_plugins", [])):
                    try:
                        await plugin.on_shutdown(app)
                    except Exception as e:
                        logger.warning(f"\u26a0\ufe0f  Plugin '{plugin.name}' on_shutdown failed: {e}")

                if watcher_task:
                    watcher_task.cancel()
                    try:
                        await watcher_task
                    except asyncio.CancelledError:
                        pass
                    
        kwargs["lifespan"] = basis_lifespan
        super().__init__(*args, **kwargs)

        @self.middleware("http")
        async def clear_basis_registries_middleware(request: Request, call_next):
            from basis.shared.store import Store
            from basis.shared.base_component import BaseComponent
            from basis.shared.router import Route

            # Reset global registries to isolate per-request SSR state and avoid DetachedInstanceError.
            # RPC endpoints are EXEMPT: store-bound @server_action methods must be able to resolve
            # their (persistent) store instance — see Store._store_blueprints / Store.reinstantiate.
            if request.url.path != "/basis/api/action":
                Store._registry.clear()
                Store._pending_subscriptions.clear()
                BaseComponent._instance_registry.clear()
                BaseComponent._pending_subscriptions.clear()
                Route._route_registry.clear()

            response = await call_next(request)
            return response

        # HMR WebSocket endpoint — registered exactly once (regardless of how many
        # component directories are mounted) so the client always has a stable /ws/hmr.
        self.websocket("/ws/hmr")(self.hmr_websocket_endpoint)

    def get_component_pyscript_vfs_path(self, component:"Component"):
        try:
            component_module_file = Path(inspect.getfile(component))
        except (TypeError, OSError):
            # Dynamic / -c defined classes have no source file.
            return None

        if not component_module_file:
            return None

        for m in self._component_routes:
            c_dir = Path(m.app.directory).absolute()
            if component_module_file.is_relative_to(c_dir):
                # The module file for that component lives under this mount's dir.
                rel = component_module_file.relative_to(c_dir)
                module_path = mount_to_module_name(m.path, rel)
                if module_path:
                    return module_path

    def include_store(self, name: str, url: str = None, target: str = None):
        for cfg in self._global_stores:
            if cfg.get("name") == name:
                return self
        self._global_stores.append({
            'name': name,
            'url': url,
            'target': target
        })
        return self

    def add_to_region(
        self,
        region: str,
        component_cls,
        *,
        props: dict | None = None,
        order: int | None = None,
        position: str = "end",
        owner: str | None = None,
    ):
        """Register a component class into *region* (the app-level primitive).

        Identity is ``(region, class)``: re-adding the same class replaces the
        existing entry (HMR-safe). Ordering: declaration order (append) by
        default, overridable by ``order=`` (int sort key); ``position="start"``
        prepends. Returns a ``RegionHandle`` disposer. See ROADMAP-SPATIAL.md.
        """
        from basis.shared.region import (
            MIN_ORDER,
            RegionContribution,
            RegionHandle,
            _register_contribution,
        )
        if position == "start" and order is None:
            order = MIN_ORDER
        contrib = RegionContribution(
            region=region,
            component_cls=component_cls,
            props=props or {},
            order=order,
            owner=owner,
            seq=self._region_seq,
        )
        self._region_seq += 1
        _register_contribution(self, contrib)
        return RegionHandle(contrib, app=self, owner=owner)

    def remove_from_region(self, region: str, component_cls) -> bool:
        """Remove every contribution of *component_cls* from *region*."""
        from basis.shared.region import _unregister_contribution, cls_path_of
        removed = False
        for contrib in list(getattr(self, "_regions", {}).get(region, [])):
            if contrib.cls_path == cls_path_of(component_cls):
                _unregister_contribution(self, contrib)
                removed = True
        return removed

    def _has_route(self, *, path: str | None = None, name: str | None = None) -> bool:
        """True if a route already matches the given path and/or name."""
        for r in self.routes:
            if path is not None and getattr(r, "path", None) == path:
                return True
            if name is not None and getattr(r, "name", None) == name:
                return True
        return False

    def include_offline_pyscript(self, mount_path: str = "/pyscript"):
        if self._has_route(name="pyscript") or self._has_route(path=mount_path):
            return
        pyscript_mount = Mount(mount_path, BasisStaticFiles(packages=[("basis", "static/pyscript")]), name="pyscript")
        self.routes.append(pyscript_mount)

    def include_pyscript_json(self, mount_path: str = "/pyscript.json"):
        if self._has_route(path=mount_path):
            return
        self.add_route(mount_path, pyscript_json, methods=['get'])

    def _get_static_files_cls(self):
        return BasisStaticFilesPyc if getattr(self, "pyc_mode", False) else BasisStaticFiles

    def include_components_dir(self, mount_path: str, dir_path: str, name: str):
        if any(getattr(r, "path", None) == mount_path for r in self._component_routes):
            return None

        static_cls = self._get_static_files_cls()
        m = Mount(mount_path, static_cls(directory=dir_path), name=name)

        self.routes.append(m)
        self._component_routes.append(m)
        self._invalidate_plugin_importers()
        return m

    def include_framework(self):
        static_cls = self._get_static_files_cls()

        if not self._has_route(name="basis_client"):
            client_mount = Mount("/basis/client", static_cls(packages=[('basis', 'client')]), name='basis_client')
            self.routes.append(client_mount)

        if not self._has_route(name="basis_shared"):
            shared_mount = Mount("/basis/shared", static_cls(packages=[('basis', 'shared')]), name='basis_shared')
            self.routes.append(shared_mount)

    def include_ui_components(self):
        if self._has_route(name="basis_ui") or self._has_route(path="/basis/ui/"):
            return

        spec = importlib.util.find_spec("basis.ui")

        ui_path = Path(spec.origin).parent

        static_cls = self._get_static_files_cls()
        ui_mount = Mount("/basis/ui/", static_cls(directory=ui_path), name='basis_ui')

        self.routes.append(ui_mount)
        self._component_routes.append(ui_mount)

    def include_page(
        self,
        path: str,
        *,
        page_cls=None,
        name: str | None = None,
    ):
        """
        Register a GET route that server-renders a Page.

        The Page is a complete recipe — ``root_component``, ``stores``, ``title``
        and PyScript config all live on the class. ``root_component`` may be
        ``None`` for a static page (no reactive root).

        Usable as a method (``app.include_page(path, page_cls=MyPage)``) or as a
        decorator on a Page subclass (``@app.include_page(path)``). Returns the
        Page class so it works as a decorator.

        Parameters
        ----------
        path:
            The URL path, e.g. "/" or "/admin".
        page_cls:
            The Page subclass to serve (required; carries root, stores, title).
        name:
            Optional route name.
        """
        # Decorator form: @app.include_page("/admin")
        if page_cls is None:
            def _register_page(cls):
                return self.include_page(path=path, page_cls=cls, name=name)
            return _register_page

        from basis.shared.page import Page

        if not (isinstance(page_cls, type) and issubclass(page_cls, Page)):
            raise TypeError(
                f"include_page(path={path!r}) requires a Page subclass, got "
                f"{page_cls!r}. To expose a root Component as a page, use "
                f"@app.page(path=...) instead."
            )

        from basis.server.ssr import render_page_ssr

        async def _ssr_handler(request: Request):

            from basis.shared.context import base_url_var

            # Set the base URL context for this request lifecycle
            token = base_url_var.set(str(request.base_url))
            try:
                html = await render_page_ssr(
                    request,
                    page_cls,
                    global_stores=self._global_stores,
                )
                return HTMLResponse(html)
            finally:
                base_url_var.reset(token)

        self.add_route(path, _ssr_handler, methods=['GET'], name=name)
        return page_cls

    def bootstrap(self, include_offline_pyscript=True):
        if getattr(self, "_bootstrapped", False):
            return
        self._bootstrapped = True
        self.include_offline_pyscript()
        self.include_pyscript_json()
        self.include_framework()
        self.include_ui_components()
        self.include_server_actions()
        self.include_plugins_projection()

        # --- Auto-discover conventional directories (components/, stores/) ---
        # Mounts them with package-derived paths (isomorphic VFS namespace) and
        # imports stores/ modules so their module-scope instances register.
        self._auto_discover_dirs()
        self._discovered_store_modules = self._auto_import_stores()

        # App-global plugin registry store ($plugins) — the control plane for
        # live plugin management. Reactive on the client, server-authoritative
        # state (a projection of _plugin_registrations).
        from basis.shared.plugin_registry import PluginRegistryStore
        if not hasattr(self, "plugins"):
            self.plugins = PluginRegistryStore("plugins")
            self.plugins.__dict__["_app"] = self
        self.include_store("plugins")

        # App-global region store ($regions) — the spatial control plane (a
        # reactive projection of app._regions; see ROADMAP-SPATIAL.md).
        from basis.shared.region import RegionStore
        if not hasattr(self, "regions"):
            self.regions = RegionStore("regions")
            self.regions.__dict__["_app"] = self
        self.include_store("regions")

        # --- Auto-discover plugins ---
        self._auto_discover_plugins()

    def include_server_actions(self, mount_path: str = "/basis/api/action"):
        """Register the single RPC endpoint for server actions.

        Every action — ``@server_action`` or ``@plugin.action`` — is dispatched
        by its canonical ``module.qualname`` path against the shared pipeline in
        :mod:`basis.server.rpc`.
        """
        from basis.server.rpc import make_action_handler

        if self._has_route(path=mount_path):
            return
        self.add_route(
            mount_path,
            make_action_handler(self),
            methods=["POST"],
            name="basis_action",
        )


    def include_plugins_projection(self, mount_path: str = "/basis/api/plugins"):
        """Register the ``$plugins`` listing endpoint (``GET /basis/api/plugins``)."""
        if self._has_route(path=mount_path):
            return

        async def _plugins_projection_handler(request: Request):
            from fastapi.responses import JSONResponse
            from basis.shared.plugin_registry import _plugin_listing
            return JSONResponse(_plugin_listing(self))

        self.add_route(mount_path, _plugins_projection_handler, methods=["GET"], name="basis_plugins_projection")

    def _auto_discover_dirs(self):
        """
        Mount conventional subdirectories (``components/``, ``stores/``) with
        package-derived mount paths so the client VFS namespace equals the
        filesystem import namespace (isomorphism). Idempotent: an existing
        mount wins. A conventional dir is only discovered if it is a real
        Python package (has ``__init__.py``); otherwise it is skipped with a
        warning (see ``_discover_conventional_dirs``).
        """
        self._discovered_dirs = {}
        for cfg in _discover_conventional_dirs(
            self._app_dir, self._components_dir, self._stores_dir
        ):
            mount = "/" + cfg["pkg"].replace(".", "/") + "/"
            # Starlette strips the trailing slash from Mount paths; compare the
            # normalized form for idempotency.
            mount_key = mount.rstrip("/")
            if any(getattr(r, "path", None) == mount_key for r in self._component_routes):
                logger.debug(
                    f"Isomorphism: {mount} already registered; "
                    f"skipping auto-discovery of {cfg['dir']}"
                )
                continue
            self.include_components_dir(mount, str(cfg["dir"]), name=cfg["name"])
            self._discovered_dirs[cfg["name"]] = cfg | {"mount": mount}
            logger.info(
                f"🗂️  Auto-discovered {cfg['subdir']}/ at {mount} "
                f"(package {cfg['pkg']})"
            )

    def _auto_import_stores(self) -> list[str]:
        """
        Import every module in the discovered ``stores/`` directory so its
        module-scope store instances register their persistent blueprints.

        Returns the dotted module names, which are also emitted to the client
        (``#basis-store-imports``) so PyScript imports the same modules, creates
        the same instances and hydrates them from ``#basis-initial-state``.
        """
        stores_cfg = self._discovered_dirs.get("stores")
        if not stores_cfg:
            return []
        stores_dir = Path(stores_cfg["dir"])
        pkg = stores_cfg["pkg"]
        modules = []
        for f in sorted(stores_dir.glob("*.py")):
            if f.name.startswith("_"):
                continue
            module_name = f"{pkg}.{f.stem}"
            try:
                importlib.import_module(module_name)
                modules.append(module_name)
            except Exception as e:
                logger.warning(
                    f"⚠️  Failed to import store module '{module_name}': {e}"
                )
        return modules

    def _auto_discover_plugins(self):
        """
        Discover and register plugins from the local ``plugins/`` directory
        and from installed packages (via ``entry_points``).

        Registration order follows ``requires`` dependencies (topological): a
        discovered plugin is registered after the plugins it depends on, and a
        missing required plugin (or a dependency cycle) fails loudly.
        """
        # Layer 1: Local plugins/ directory (always — inherently app-scoped)
        local = discover_local_plugins(self._app_dir, self._plugins_dir)

        # Layer 2: Installed plugins via entry_points (with optional filtering)
        installed = []
        if self._plugins_config is not False:
            allowlist = (
                self._plugins_config
                if isinstance(self._plugins_config, list)
                else None
            )
            installed = discover_installed_plugins(
                allowlist=allowlist, blocklist=self._exclude_plugins
            )

        discovered = _topo_sort_plugins(
            local + installed,
            registered_names={p.name for p in self._plugins},
        )
        for plugin in discovered:
            self.include_plugin(plugin)

    def _detect_app_directory(self) -> Path:
        """
        Determine the filesystem directory of the application that created
        this Basis instance.  Uses the caller's ``__file__`` from the import
        stack, falling back to ``cwd()``.
        """
        # Walk up the call stack to find the first frame outside of basis itself
        for frame_info in inspect.stack():
            frame_file = frame_info.filename
            if "basis/server/" not in frame_file and "basis/shared/" not in frame_file:
                return Path(frame_file).parent.resolve()
        return Path.cwd()

    def include_plugin(self, plugin: BasisPlugin):
        """
        Register a BasisPlugin with this Basis app.

        This method is **idempotent** — calling it with the same plugin
        instance or a plugin with the same ``name`` is silently ignored.

        Steps performed in order:

        1. **Dedup check** — skip if already registered.
        2. **Routes** — mounts all HTTP endpoints declared on ``plugin.router``.
        3. **Static files** — if ``plugin.static_dir`` is set and exists on
           disk, serves that directory at ``plugin.static_mount``.
        4. **SSR page** — if the plugin has a ``root_component`` attribute.
        5. **Models** — merges the plugin's model set into the app.
        6. **Tracking** — appends to ``_plugins``.
        7. **on_register hook** — calls ``plugin.on_register(app)``.

        Parameters
        ----------
        plugin:
            A :class:`~basis.server.plugin.BasisPlugin` instance.

        Returns
        -------
        PluginRegistration
            The revertible registration record (used by ``remove_plugin`` /
            ``disable_plugin``). Returns the existing record when the include is
            a no-op.
        """
        if not hasattr(self, "_plugins"):
            self._plugins = []

        # Idempotent: skip if already registered (by identity or name).
        for existing in self._plugins:
            if existing is plugin or existing.name == plugin.name:
                logger.debug(f"Plugin '{plugin.name}' already registered, skipping.")
                return self._plugin_registrations.get(plugin.name)

        # Dependency enforcement: a plugin whose required plugin is not yet
        # registered fails loudly. Discovery topo-sorts, so this only bites
        # manual include order — the error names exactly what to fix.
        missing = [r for r in plugin.requires if r not in {p.name for p in self._plugins}]
        if missing:
            raise ValueError(
                f"Plugin '{plugin.name}' requires {missing} which are not "
                f"registered. Register its dependencies first "
                f"(app.include_plugin(dep)) or check the plugins/ directory "
                f"for the provider."
            )

        reg = PluginRegistration(plugin=plugin)

        # 1. Wire all HTTP routes declared on the plugin's router.
        reg.added_routes.extend(self._capture_added_routes(
            lambda: self.include_router(plugin.router)
        ))

        # 2. Serve static/component files so PyScript can load them.
        if plugin.static_dir and plugin.static_dir.exists():
            reg.component_mount = self.include_components_dir(
                plugin.static_mount,
                str(plugin.static_dir),
                name=plugin.name,
            )
            # Isomorphism guard for plugin-served components: the static mount
            # must reproduce the plugin dir's package path so VFS == filesystem.
            pkg = _resolve_canonical_package(Path(plugin.static_dir).absolute())
            if pkg is not None:
                expected = "/" + pkg.replace(".", "/")
                actual = (plugin.static_mount or "").rstrip("/")
                if actual != expected:
                    logger.warning(
                        f"⚠️  Plugin '{plugin.name}' static_mount '{actual}' does "
                        f"not reproduce package path '{expected}' — client VFS "
                        f"names will not match the filesystem (isomorphism "
                        f"violation)."
                    )

        # 3. Optional SSR page (synthesized from the plugin's root component).
        if hasattr(plugin, "root_component") and plugin.root_component:
            try:
                entry_module = f"/{Path(inspect.getfile(plugin.root_component)).name}"
            except (TypeError, OSError):
                entry_module = "/basis/client/entrypoint.py"
            plugin_page = _synthesize_page(
                plugin.root_component,
                entry_module=entry_module,
            )
            reg.added_routes.extend(self._capture_added_routes(
                lambda: self.include_page(plugin.prefix or "/", page_cls=plugin_page)
            ))

        # 4. Register the plugin's models into the app's models set.
        if not hasattr(self, "models"):
            self.models = set()
        if hasattr(plugin, "models"):
            reg.models = set(plugin.models)
            self.models.update(reg.models)

        # 4b. Make the plugin's server actions reachable by their canonical path
        #     (module.qualname) in the global action registry, so the single RPC
        #     endpoint dispatches them by path. Re-applied on re-enable.
        reg.action_registry_entries = dict(
            getattr(plugin, "_action_registry_entries", {})
        )
        from basis.shared.actions import _action_registry
        for rpc_path, wrapper in reg.action_registry_entries.items():
            _action_registry[rpc_path] = wrapper

        # 5. Track included plugins + the revertible registration record.
        self._plugins.append(plugin)
        self._plugin_registrations[plugin.name] = reg

        # 6. Call on_register lifecycle hook
        try:
            plugin.on_register(self)
        except Exception as e:
            logger.error(f"\u274c Plugin '{plugin.name}' on_register failed: {e}")
            raise

        # 6b. Region contributions declared by the plugin (module scope and/or
        #     on_register) are flushed into the app registry and recorded on the
        #     registration so disable/remove can unwind them (ROADMAP-SPATIAL.md).
        from basis.shared.region import _register_contribution
        plugin._app = self
        pending = list(getattr(plugin, "_region_items", []) or [])
        reg.region_items = list(pending)
        for contrib in pending:
            contrib.seq = self._region_seq
            self._region_seq += 1
            _register_contribution(self, contrib)

        # 7. HMR watcher must re-derive its file map for the new mount.
        self._after_plugin_change()
        return reg

    def _capture_added_routes(self, fn) -> list:
        """Run *fn* and return the route objects it added to the app (by identity)."""
        before = {id(r) for r in self.routes}
        fn()
        return [r for r in self.routes if id(r) not in before]

    def _refresh_plugin_registry(self):
        """Keep the app-owned ``$plugins`` store's projection in sync after a
        plugin is included/removed. (Per-request SSR instances refresh on app
        attach; the app-owned instance refreshes here.)"""
        plugins = getattr(self, "plugins", None)
        if plugins is not None:
            refresh = getattr(plugins, "_refresh_from_app", None)
            if refresh is not None:
                refresh()

    def _after_plugin_change(self, rebuild_vfs: bool = False):
        """Post-registration bookkeeping shared by include/remove/enable_plugin.

        Rebuilds the client VFS manifest when the plugin's *files* changed
        (remove/enable prune or restore the static mount), and always re-derives
        the HMR file map, the ``$plugins`` projection and the plugin→importers
        cache so they match the current plugin set.
        """
        if rebuild_vfs:
            initialize_pyscript_registry(self)
        self._hmr_map_dirty = True
        self._refresh_plugin_registry()
        self._invalidate_plugin_importers()

    def _plugin_importers(self) -> dict[str, list[str]]:
        """Map each enabled plugin to the client modules that import it directly.

        AST-scans every served component file (app ``components/``/``stores/``
        and plugin static dirs) for imports of plugin-owned packages. A plain
        list of direct importers per plugin — no transitive closure: a plugin
        is *essential* (pinned) iff any enabled consumer imports it, and the
        importer names give the reason surfaced when unloading is refused.

        Only plugins with a resolvable package path (a real package under a
        conventional layout) are tracked; everything else is treated as
        optional/disableable.

        The result is cached (``_plugin_importers_cache``): warmed once at app
        load alongside the client VFS manifest, and invalidated whenever the
        plugin set or a component-dir mount changes — so remove/disable is O(1)
        instead of re-scanning every served file each time.
        """
        cached = getattr(self, "_plugin_importers_cache", None)
        if cached is not None:
            return cached

        from basis.server.ast_utils import collect_imported_modules

        # plugin name -> canonical package prefix it owns (e.g. "jotter.plugins").
        plugin_packages: dict[str, str] = {}
        for name, reg in self._plugin_registrations.items():
            if reg.disposed:
                continue
            mount = reg.component_mount
            if mount is None:
                continue
            pkg = _resolve_canonical_package(Path(mount.app.directory).absolute())
            if pkg:
                plugin_packages[name] = pkg
        if not plugin_packages:
            self._plugin_importers_cache = {}
            return {}

        # consumer module name -> source file (every served component dir).
        consumers: dict[str, Path] = {}
        for m in self._component_routes:
            watch_dir = Path(m.app.directory).absolute()
            if not watch_dir.exists():
                continue
            for f in watch_dir.rglob("*.py"):
                if "__pycache__" in f.parts:
                    continue
                module_name = mount_to_module_name(m.path, f.relative_to(watch_dir))
                if module_name is not None:
                    consumers[module_name] = f

        importers: dict[str, list[str]] = {}
        for module_name, file in consumers.items():
            # A plugin's own package files are not consumers of itself.
            own_plugin = None
            for pname, pkg in plugin_packages.items():
                if module_name == pkg or module_name.startswith(pkg + "."):
                    own_plugin = pname
                    break
            try:
                source = file.read_text(encoding="utf-8")
            except OSError:
                continue
            for imported in collect_imported_modules(source):
                for pname, pkg in plugin_packages.items():
                    if pname == own_plugin:
                        continue
                    if imported == pkg or imported.startswith(pkg + "."):
                        importers.setdefault(pname, [])
                        if module_name not in importers[pname]:
                            importers[pname].append(module_name)
        self._plugin_importers_cache = importers
        return importers

    def _invalidate_plugin_importers(self):
        """Drop the cached plugin→importers map after a structural change.

        Called by plugin include/remove/enable and by ``include_components_dir``
        (the consumer-file set changed), so the next ``_plugin_importers()``
        recomputes from the current mounts.
        """
        if hasattr(self, "_plugin_importers_cache"):
            self._plugin_importers_cache = None

    async def remove_plugin(self, name_or_plugin, *, force: bool = False) -> bool:
        """
        Unmount a registered plugin and unwind every registration it made.

        Reverts the plugin's routes, component mount (from both the app route
        list and the class-level ``_component_routes``), models, and its action
        surface (``_plugins``), rebuilds the PyScript VFS manifest + HMR file
        map, resets the OpenAPI cache, and runs the plugin's ``on_shutdown``
        hook. The plugin object is kept (as a disposed registration) so
        :meth:`enable_plugin` can re-register it later.

        Refuses (returns ``False``) when a client module imports the plugin
        directly — unloading it would prune the client VFS and break the next
        page load. Pass ``force=True`` to override (the client bundle will then
        fail to import the plugin on the next load).

        Returns ``True`` if a plugin was unmounted, ``False`` if it was not
        registered (or already unmounted, or refused as imported).
        """
        name = name_or_plugin if isinstance(name_or_plugin, str) else getattr(name_or_plugin, "name", None)
        if not name:
            return False
        reg = self._plugin_registrations.get(name)
        if reg is None or reg.disposed:
            return False
        if not force:
            pinned = self._plugin_importers().get(name)
            if pinned:
                logger.warning(
                    f"⚠️  Plugin '{name}' is imported by "
                    f"{', '.join(sorted(pinned))} — refusing to unload. Remove "
                    f"the import or pass force=True."
                )
                return False
        reg.disposed = True

        # 1. Routes added by the plugin's router + synthesized page.
        for r in reg.added_routes:
            try:
                self.routes.remove(r)
            except ValueError:
                pass

        # 2. Component mount — lives in BOTH the app route list and the
        #    class-level _component_routes (shared across Basis instances).
        if reg.component_mount is not None:
            try:
                self.routes.remove(reg.component_mount)
            except ValueError:
                pass
            try:
                self._component_routes.remove(reg.component_mount)
            except ValueError:
                pass

        # 3. Models contributed by the plugin.
        if hasattr(self, "models") and reg.models:
            self.models -= reg.models

        # 3b. Region contributions contributed by the plugin.
        if getattr(reg, "region_items", None):
            from basis.shared.region import _unregister_contribution
            for contrib in reg.region_items:
                _unregister_contribution(self, contrib)
            reg.region_items = []

        # 4. Remove from _plugins, and unregister its actions from the global
        #    registry so a disabled plugin's actions are no longer callable.
        if reg.plugin in self._plugins:
            self._plugins.remove(reg.plugin)
        from basis.shared.actions import _action_registry
        for rpc_path in reg.action_registry_entries:
            _action_registry.pop(rpc_path, None)

        # 5. OpenAPI cache (routes changed).
        if hasattr(self, "openapi_schema"):
            self.openapi_schema = None

        # 6. Lifecycle teardown, then post-removal bookkeeping (VFS prune + HMR map
        #    + $plugins projection + importer cache).
        try:
            await reg.plugin.on_shutdown(self)
        except Exception as e:
            logger.warning(f"⚠️  Plugin '{name}' on_shutdown failed during remove: {e}")

        self._after_plugin_change(rebuild_vfs=True)
        logger.info(f"🔌 Removed plugin '{name}' (routes, mount, models, actions unwound).")
        return True

    async def disable_plugin(self, name, *, force: bool = False) -> bool:
        """Unmount a plugin, keeping it re-enableable (mirrors Cordis ``disabled: true``).

        Refuses (returns ``False``) when the plugin is imported by a client
        module unless ``force=True`` — same guard as :meth:`remove_plugin`.
        """
        return await self.remove_plugin(name, force=force)

    async def enable_plugin(self, name: str) -> bool:
        """Re-mount a previously disabled plugin (by name) and run its startup hook."""
        reg = self._plugin_registrations.get(name)
        if reg is None or not reg.disposed:
            return False
        plugin = reg.plugin
        self.include_plugin(plugin)  # fresh registration replaces the disposed record
        # Re-include the plugin's static mount in the PyScript VFS manifest
        # (mirrors remove_plugin's prune). Without this, a disable→enable cycle
        # leaves the manifest pruned and the client can no longer import the
        # plugin's modules on the next page load (broken SSR boot).
        self._after_plugin_change(rebuild_vfs=True)
        try:
            await plugin.on_startup(self)
        except Exception as e:
            logger.warning(f"⚠️  Plugin '{name}' on_startup failed after re-enable: {e}")
        return True

    def page(
        self,
        component_cls=None,
        *,
        path: str = "/",
        page_cls=None,
        title: str | None = None,
        pyscript_src: str = ONLINE_PYSCRIPT,
        name: str | None = None,
    ):
        """
        Turn a root Component into a page at ``path`` (default ``"/"``) in one go:
        bootstrap, synthesize a Page shell carrying the decorated component as its
        root, register the SSR route, and serve the component's directory.

        ``@app.page`` decorates a *root component* (a ``Component`` subclass) —
        never a ``Page``. It is the "quick and dirty" path: page-level ``stores``
        are NOT supported here (the client boots from the component file, so it
        cannot hydrate page stores). To declare page stores, write a ``Page``
        subclass and register it with ``@app.include_page(path)`` or
        ``app.include_page(path, page_cls=MyPage)``.

        Returns the decorated component class.
        """
        # Support both `@app.page` (bare) and `@app.page(path=..., ...)` (with args).
        if component_cls is None:
            return functools.partial(
                self.page,
                path=path,
                page_cls=page_cls,
                title=title,
                pyscript_src=pyscript_src,
                name=name,
            )

        from basis.shared.page import Page as PageBase

        # Contract: @app.page decorates a root Component, not a Page shell.
        if isinstance(component_cls, type) and issubclass(component_cls, PageBase):
            raise TypeError(
                f"{component_cls.__name__} is a Page, not a root component. "
                "A Page is the document shell.\n"
                f"  • To expose a root component: decorate a Component with @app.page(path=...)\n"
                f"  • To register a Page: decorate it with @app.include_page(path) "
                f"or app.include_page(path, page_cls={component_cls.__name__})"
            )

        self.bootstrap()

        # Detect where the component was defined to serve that directory
        try:
            component_file = Path(inspect.getfile(component_cls)).absolute()
        except (TypeError, OSError):
            # Fallback to the file that called page()
            caller_frame = inspect.stack()[1]
            component_file = Path(caller_frame.filename).absolute()

        app_dir = component_file.parent

        # Isomorphism: if the component's file is already served by a discovered
        # component dir (e.g. components/), its VFS import name equals the
        # filesystem name and we must NOT add an automatic "/" mount — that would
        # create a second, non-isomorphic namespace. Only a bare single-file app
        # (the component file is inside no registered component dir) falls back
        # to the "/" mount.
        covered_module = self.get_component_pyscript_vfs_path(component_cls)
        if covered_module:
            entry_module = _component_entry_url(self, component_file)
        else:
            entry_module = f"/{component_file.name}"

        # Synthesize the page shell carrying this component as its root.
        synthesized = _synthesize_page(
            component_cls,
            page_cls=page_cls,
            title=title,
            entry_module=entry_module,
            pyscript_src=pyscript_src,
        )

        # Register the SSR page for this component
        self.include_page(path, page_cls=synthesized, name=name)

        if not covered_module:
            # Serve the application directory so PyScript can find the code.
            # Added AFTER include_page so the SSR route is matched before the
            # catch-all "/" static mount (a root Mount shadows later routes).
            self.include_components_dir("/", str(app_dir), name="app_root")

        return component_cls
