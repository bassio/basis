import asyncio
import functools
import importlib.util
import inspect
import itertools
import logging
import os
from pathlib import Path
from typing import Set
from urllib.parse import urljoin
from contextlib import asynccontextmanager
import sys
from starlette.routing import Route, Mount
from starlette.staticfiles import StaticFiles
from basis.server.static import BasisStaticFiles, BasisStaticFilesPyc
from fastapi import FastAPI, APIRouter, Request, WebSocket, WebSocketDisconnect
from basis.server.plugin import BasisPlugin
from fastapi.responses import JSONResponse, HTMLResponse

from basis.server.db import DBAppMixin


ONLINE_PYSCRIPT = "https://pyscript.net/releases/2026.3.1"

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


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
    files_dict["{DOMAIN}/basis/client/entrypoint_csr.py"] = "./basis/client/entrypoint_csr.py"
    files_dict["{DOMAIN}/basis/client/entrypoint_ssr.py"] = "./basis/client/entrypoint_ssr.py"

    client_py_files = [
        "component.py",
        "plugin.py",
        "actions.py",
        "plugins.py",
    ]
    for f_name in client_py_files:
        stem = Path(f_name).stem
        target_name = stem + py_ext # py_ext depends on whether pyc mode is enabled or not
        files_dict[f"{{DOMAIN}}/basis/client/{target_name}"] = f"./basis/client/{target_name}"
    
    files_dict["{DOMAIN}/basis/client/component.js"] = "./basis/client/component.js"

    # add shared
    shared_py_files = [
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
        "actions.py",
        "plugin.py",
        "router.py",
        "db.py",
        "basis_await.py",
        "validation.py",
    ]
    for f_name in shared_py_files:
        stem = Path(f_name).stem
        target_name = stem + py_ext
        files_dict[f"{{DOMAIN}}/basis/shared/{target_name}"] = f"./basis/shared/{target_name}"

    for i, m in enumerate(app._component_routes, 1):
        cdir_n_label = '{' + f'COMPONENTS_DIR_{i}' + '}'
        mount_path = m.path   # mount path
        c_dir = Path(m.app.directory).absolute()
        
        # Ensure clean mount path starting with '/' and without trailing '/' for URL logic
        clean_mount = mount_path
        if not clean_mount.startswith("/"):
            clean_mount = "/" + clean_mount
        clean_mount = clean_mount.rstrip("/")
        
        files_dict[cdir_n_label] = "{DOMAIN}" + clean_mount

        if not c_dir.exists():
            continue

        for f in itertools.chain(c_dir.glob("*.py"), c_dir.glob("**/*.py")):
            subdir = f.parent
            subdir_rel_to_cdir = subdir.relative_to(c_dir)
            
            vfs_file_name = f.stem + py_ext if pyc_mode else f.name
            
            # component_file uses '/' as path separator in PyScript VFS
            component_file = cdir_n_label + "/" + (subdir_rel_to_cdir / vfs_file_name).as_posix()
            component_file = component_file.replace("//", "/")

            # Server relative URL must always start with './' and use POSIX path separators
            files_dict[component_file] = "." + clean_mount + "/" + (subdir_rel_to_cdir / vfs_file_name).as_posix()
            files_dict[component_file] = files_dict[component_file].replace("//", "/")

            # Translate file path to Python import path
            mount_parts = [p for p in clean_mount.split("/") if p]
            parts = mount_parts + list(subdir_rel_to_cdir.parts) + [f.stem]
            parts = [p for p in parts if p]
            if parts and parts[-1] == "__init__":
                parts.pop()
            if not parts:
                continue
            vfs_module_path = ".".join(parts)
            
            if vfs_module_path not in client_modules:
                client_modules.append(vfs_module_path)

            if f.name == "__init__.py":
                # get the name of the package (parent folder name)
                css_file = (f.parent / f.parent.name).with_suffix(".css")
                html_file = (f.parent / f.parent.name).with_suffix(".html")
            else:
                css_file = f.with_suffix(".css")
                html_file = f.with_suffix(".html")

            component_assets = [css_file, html_file]
                    
            for asset in component_assets:
                if asset.exists():
                    asset_file = cdir_n_label + "/" + (subdir_rel_to_cdir / asset.name).as_posix()
                    asset_file = asset_file.replace("//", "/")
                    
                    files_dict[asset_file] = "." + clean_mount + "/" + (subdir_rel_to_cdir / asset.name).as_posix()
                    files_dict[asset_file] = files_dict[asset_file].replace("//", "/")

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


class HMRManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.active_connections.remove(connection)

class Basis(FastAPI, DBAppMixin):
    
    _component_dirs = []
    _component_routes = []
    _global_stores = []
    hmr_manager = HMRManager()

    def __init__(self, *args, plugins_dir: str = "plugins",
                 plugins: list[str] | bool | None = None,
                 exclude_plugins: list[str] | None = None,
                 pyc_mode: bool = False,
                 **kwargs):
        # Client-side HMR is enabled by default for dev via the BASIS_HMR env var
        # (set by ``basis dev --hmr``), or programmatically via run_with_hmr().
        self._start_hmr_watcher = os.environ.get("BASIS_HMR", "").lower() in ("1", "true", "yes")
        self._plugins_dir = plugins_dir
        # plugins=True/None → auto-discover all; plugins=["a","b"] → allowlist;
        # plugins=False → disable installed-plugin discovery (local still works)
        self._plugins_config = plugins
        self._exclude_plugins = exclude_plugins or []
        self.pyc_mode = pyc_mode or os.environ.get("BASIS_PYC_MODE", "").lower() in ("1", "true", "yes")
        if not hasattr(self, "_plugins"):
            self._plugins = []
        # Capture the app directory now (call stack has the user's module)
        self._app_dir = self._detect_app_directory()

        user_lifespan = kwargs.get("lifespan")
        
        @asynccontextmanager
        async def basis_lifespan(app):
            # Ensure bootstrap is called
            app.bootstrap()
            
            # Precompute PyScript VFS files and action mappings
            initialize_pyscript_registry(app)

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
            if request.url.path not in ("/basis/api/action", "/basis/api/plugin-action"):
                Store._registry.clear()
                Store._pending_subscriptions.clear()
                BaseComponent._instance_registry.clear()
                BaseComponent._pending_subscriptions.clear()
                Route._route_registry.clear()

            response = await call_next(request)
            return response

        # HMR WebSocket endpoint — registered exactly once (regardless of how many
        # component directories are mounted) so the client always has a stable /ws/hmr.
        @self.websocket("/ws/hmr")
        async def hmr_websocket_endpoint(websocket: WebSocket):
            await self.hmr_manager.connect(websocket)
            try:
                while True:
                    await websocket.receive_text()  # Just keep connection alive
            except WebSocketDisconnect:
                self.hmr_manager.disconnect(websocket)
            except Exception:
                self.hmr_manager.disconnect(websocket)

    def get_component_pyscript_vfs_path(self, component:"Component"):
        
        component_module_file = Path(inspect.getfile(component))
        
        if not component_module_file:
            return None

        for i, m in enumerate(self._component_routes, 1):
            #print(f"* Mount Point: '{m.path}' (Name: '{m.name}')")
            # The directory path is stored in route.app.directory
            #print(f"  Serving directory: '{Path(m.app.directory).absolute()}'")
            
            mount_path = m.path   # mount path
            # Ensure clean mount path starting with '/' and without trailing '/' for URL logic
            clean_mount = mount_path
            if not clean_mount.startswith("/"):
                clean_mount = "/" + clean_mount
            clean_mount = clean_mount.rstrip("/")

            # Ensure clean mount path starting with '/' and without trailing '/' for URL logic
        
            c_dir = Path(m.app.directory).absolute()

            if component_module_file.is_relative_to(c_dir):
                #i.e. the module file for that component is contained within this mount point's c_dir
                subdir = component_module_file.parent
                subdir_rel_to_cdir = subdir.relative_to(c_dir)
            
                # Server relative URL must always start with './' and use POSIX path separators
                vfs_file = "." + clean_mount + "/" + (subdir_rel_to_cdir / component_module_file.name).as_posix()
                vfs_file = vfs_file.replace("//", "/")

                # Translate file path to Python import path
                mount_parts = [p for p in clean_mount.split("/") if p]
                parts = mount_parts + list(subdir_rel_to_cdir.parts) + [component_module_file.stem]
                parts = [p for p in parts if p]
                if parts and parts[-1] == "__init__":
                    parts.pop()
                if parts:
                    module_path = ".".join(parts)
                    return module_path

    def include_store(self, name: str, url: str = None, target: str = None):
        self._global_stores.append({
            'name': name,
            'url': url,
            'target': target
        })
        return self

    def include_offline_pyscript(self, mount_path:str="/pyscript"):
        for r in self.routes:
            if getattr(r, "name", None) == "pyscript" or getattr(r, "path", None) == mount_path:
                return
        pyscript_mount = Mount(mount_path, BasisStaticFiles(packages=[("basis", "static/pyscript")]), name="pyscript")
        self.routes.append(pyscript_mount)
    
    def include_pyscript_json(self, mount_path:str="/pyscript.json"):
        for r in self.routes:
            if getattr(r, "path", None) == mount_path:
                return
        self.add_route(mount_path, pyscript_json, methods=['get'])

    def _get_static_files_cls(self):
        return BasisStaticFilesPyc if getattr(self, "pyc_mode", False) else BasisStaticFiles

    def include_components_dir(self, mount_path:str, dir_path:str, name:str):
        for r in self._component_routes:
            if getattr(r, "path", None) == mount_path:
                return

        static_cls = self._get_static_files_cls()
        m = Mount(mount_path, static_cls(directory=dir_path), name=name)
        
        self.routes.append(m)
        self._component_routes.append(m)

    def _build_hmr_file_map(self):
        """
        Build ``{absolute_path: meta}`` for every watched component file.

        For ``.py`` files the meta includes the authoritative client **import
        module name** (same derivation as ``initialize_pyscript_registry``) so the
        client can reload the exact module instead of guessing from a path.
        """
        file_map = {}
        for m in self._component_routes:
            watch_dir = Path(m.app.directory).absolute()
            if not watch_dir.exists():
                continue

            clean_mount = m.path.rstrip("/")
            mount_parts = [p for p in clean_mount.split("/") if p]

            for f in itertools.chain(watch_dir.rglob("*.py"), watch_dir.rglob("*.html"), watch_dir.rglob("*.css")):
                # Never watch compiled bytecode or stray caches
                if "__pycache__" in f.parts or f.suffix == ".pyc":
                    continue
                rel = f.relative_to(watch_dir)
                meta = {"file": str(rel), "ext": f.suffix.lstrip(".")}
                if f.suffix == ".py":
                    parts = list(mount_parts) + list(rel.with_suffix("").parts)
                    if parts and parts[-1] == "__init__":
                        parts.pop()
                    if parts:
                        meta["module"] = ".".join(parts)
                file_map[str(f.absolute())] = meta
        return file_map

    async def _start_file_watcher(self):
        """Simple poller to watch for file changes and broadcast HMR events."""
        mtimes = {}
        file_map = self._build_hmr_file_map()

        # Initial scan
        watch_dirs = [Path(m.app.directory).absolute() for m in self._component_routes]

        while True:
            try:
                for watch_dir in watch_dirs:
                    if not watch_dir.exists():
                        continue
                    for f in watch_dir.rglob("*"):
                        if f.suffix not in (".py", ".html", ".css"):
                            continue
                        if "__pycache__" in f.parts:
                            continue
                        try:
                            mtime = f.stat().st_mtime
                        except OSError:
                            continue
                        if f in mtimes and mtimes[f] < mtime:
                            logger.info("HMR: File changed: %s", f.name)
                            rel_path = f.relative_to(watch_dir)
                            meta = file_map.get(str(f.absolute()), {})
                            try:
                                content = f.read_text(encoding="utf-8")
                            except OSError:
                                content = ""
                            await self.hmr_manager.broadcast({
                                "type": "hmr",
                                "file": str(rel_path),
                                "ext": meta.get("ext") or f.suffix.lstrip("."),
                                "module": meta.get("module"),
                                "content": content,
                            })
                        mtimes[f] = mtime
            except Exception as e:  # never let the watcher die
                logger.warning("HMR: watcher error: %s", e)
            await asyncio.sleep(0.5)

    def start_file_watcher(self):
        asyncio.create_task(self._start_file_watcher())

    def run_with_hmr(self, host="127.0.0.1", port=8000):
        import uvicorn
        self._start_hmr_watcher = True
        uvicorn.run(self, host=host, port=port)

    def run_without_hmr(self, host="127.0.0.1", port=8000):
        import uvicorn
            
        uvicorn.run(self, host=host, port=port)

    def include_framework(self):
        client_route = None
        shared_route = None

        for r in self.routes:
            if r.name == 'basis_client':
                client_route = r
            elif r.name == 'basis_shared':
                shared_route = r

        static_cls = self._get_static_files_cls()

        if not client_route:
            client_mount = Mount("/basis/client", static_cls(packages=[('basis', 'client')]), name='basis_client')
            self.routes.append(client_mount)

        if not shared_route:
            shared_mount = Mount("/basis/shared", static_cls(packages=[('basis', 'shared')]), name='basis_shared')
            self.routes.append(shared_mount)

    def include_ui_components(self):
        for r in self._component_routes:
            if getattr(r, "name", None) == 'basis_ui' or getattr(r, "path", None) == "/basis/ui/":
                return

        spec = importlib.util.find_spec("basis.ui")
        
        ui_path = Path(spec.origin).parent

        static_cls = self._get_static_files_cls()
        ui_mount = Mount("/basis/ui/", static_cls(directory=ui_path), name='basis_ui')

        self.routes.append(ui_mount)
        self._component_routes.append(ui_mount)

    def include_ssr_page(
        self,
        path: str,
        component_cls,
        *,
        page_cls = None,
        entry_module: str = "/main.py",
        title: str = "Basis App",
        stores: dict | None = None,
        pyscript_src: str = "/pyscript",
        pyscript_json_url: str = "/pyscript.json",
        name: str | None = None,
    ):
        """
        Register a GET route that returns a fully server-rendered HTML page.

        Parameters
        ----------
        path:
            The URL path, e.g. "/" or "/home".
        component_cls:
            A ServerComponent subclass to render for this route.
        entry_module:
            URL path for the PyScript entry .py file.
        title:
            HTML <title> for the page.
        stores:
            Dict of {name: Store instance} to embed as initial-state JSON.
        name:
            Optional route name.
        """
        if page_cls is None:
            from basis.shared.page import Page
            page_cls = Page

        from basis.server.ssr import render_page_async

        async def _ssr_handler(request: Request):

            from basis.shared.context import base_url_var
            
            # Set the base URL context for this request lifecycle
            token = base_url_var.set(str(request.base_url))
            try:
                # Merge global stores with page-specific ones
                page_stores = stores or {}
                html = await render_page_async(
                    request,
                    component_cls,
                    page_cls=page_cls,
                    title=title,
                    stores=page_stores,
                    global_stores=self._global_stores,
                    entry_module=entry_module,
                    pyscript_src=pyscript_src,
                    pyscript_json_url=str(request.url_for('pyscript_json')),
                )
                return HTMLResponse(html)
            finally:
                base_url_var.reset(token)

        self.add_route(path, _ssr_handler, methods=['GET'], name=name)


    def bootstrap(self, include_offline_pyscript=True):
        if getattr(self, "_bootstrapped", False):
            return
        self._bootstrapped = True
        self.include_offline_pyscript()
        self.include_pyscript_json()
        self.include_framework()
        self.include_ui_components()
        self.include_server_actions()
        self.include_plugin_server_actions()

        # --- Auto-discover plugins ---
        self._auto_discover_plugins()

    def include_server_actions(self, mount_path: str = "/basis/api/action"):
        """
        Registers a generic RPC endpoint for server actions.
        """
        for r in self.routes:
            if getattr(r, "path", None) == mount_path:
                return
        async def _action_handler(request: Request):
            from basis.shared.actions import _action_registry
            from basis.shared.store import Store
            from fastapi import HTTPException
            import asyncio
            
            try:
                payload = await request.json()
            except Exception:
                raise HTTPException(status_code=400, detail="Invalid JSON payload")

            path = payload.get("path")
            store_name = payload.get("store_name")
            args = payload.get("args", [])
            kwargs = payload.get("kwargs", {})

            # Resolve path using the precomputed VFS-to-Server module mapping in the Basis (Starlette) app registry
            vfs_map = getattr(request.app.state, "vfs_to_server_module", {})
            parts = path.split(".")
            for i in range(len(parts) - 1, 0, -1):
                prefix = ".".join(parts[:i])
                if prefix in vfs_map:
                    server_module = vfs_map[prefix]
                    suffix = parts[i:]
                    path = ".".join([server_module] + suffix)
                    break

            func = _action_registry.get(path)
            if not func:
                # Try to import the module if it's not registered
                if "." in path:
                    module_name = path.rsplit(".", 2)[0]
                    try:
                        importlib.import_module(module_name)
                        func = _action_registry.get(path)
                    except ImportError:
                        pass
                
            if not func:
                raise HTTPException(status_code=404, detail=f"Action '{path}' not found")

            instance = None
            if store_name:
                instance = Store._registry.get(store_name)
                if not instance:
                    # The per-request registry reset may have wiped the live instance;
                    # fall back to the persistent store blueprint registry and rebuild it.
                    instance = Store.reinstantiate(store_name)
                    if instance is not None:
                        Store._registry[store_name] = instance
                if not instance:
                    raise HTTPException(status_code=404, detail=f"Store '{store_name}' not found")

            try:
                # Execute the action
                if instance:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(instance, *args, **kwargs)
                    else:
                        result = func(instance, *args, **kwargs)
                else:
                    if asyncio.iscoroutinefunction(func):
                        result = await func(*args, **kwargs)
                    else:
                        result = func(*args, **kwargs)

                response_data = {"data": result}
                if instance:
                    response_data["new_state"] = instance.serialize()
                
                return JSONResponse(response_data)
            except Exception as e:
                import traceback
                traceback.print_exc()
                logger.error(f"Error executing server action '{path}': {e}")
                raise HTTPException(status_code=500, detail=str(e))

        self.add_route(mount_path, _action_handler, methods=["POST"], name="basis_action")

    def include_plugin_server_actions(self, mount_path: str = "/basis/api/plugin-action"):
        """
        Registers a generic RPC endpoint for plugin-scoped server actions.
        """
        has_action_route = False
        has_plugins_registry_route = False
        for r in self.routes:
            if getattr(r, "path", None) == mount_path:
                has_action_route = True
            if getattr(r, "path", None) == "/basis/api/plugins-registry":
                has_plugins_registry_route = True

        if not has_action_route:
            async def _plugin_action_handler(request: Request):
                from fastapi import HTTPException
                from fastapi.responses import JSONResponse
                
                try:
                    payload = await request.json()
                except Exception:
                    raise HTTPException(status_code=400, detail="Invalid JSON payload")

                plugin_name = payload.get("plugin_name")
                action_name = payload.get("action_name")
                store_name = payload.get("store_name")
                args = payload.get("args", [])
                kwargs = payload.get("kwargs", {})

                plugin = None
                for p in getattr(self, "_plugins", []):
                    if p.name == plugin_name:
                        plugin = p
                        break

                if not plugin:
                    raise HTTPException(status_code=404, detail=f"Plugin '{plugin_name}' not found")

                func = getattr(plugin, "actions", {}).get(action_name)
                if not func:
                    raise HTTPException(status_code=404, detail=f"Action '{action_name}' not found on plugin '{plugin_name}'")

                instance = None
                if store_name:
                    from basis.shared.store import Store
                    instance = Store._registry.get(store_name)
                    if not instance:
                        instance = Store.reinstantiate(store_name)
                        if instance is not None:
                            Store._registry[store_name] = instance
                    if not instance:
                        raise HTTPException(status_code=404, detail=f"Store '{store_name}' not found")

                try:
                    import asyncio
                    if instance:
                        if asyncio.iscoroutinefunction(func):
                            result = await func(instance, *args, **kwargs)
                        else:
                            result = func(instance, *args, **kwargs)
                    else:
                        if asyncio.iscoroutinefunction(func):
                            result = await func(*args, **kwargs)
                        else:
                            result = func(*args, **kwargs)

                    response_data = {"data": result}
                    if instance:
                        response_data["new_state"] = instance.serialize()
                    
                    return JSONResponse(response_data)
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    logger.error(f"Error executing plugin server action '{plugin_name}.{action_name}': {e}")
                    raise HTTPException(status_code=500, detail=str(e))

            self.add_route(mount_path, _plugin_action_handler, methods=["POST"], name="basis_plugin_action")

        if not has_plugins_registry_route:
            async def _plugins_registry_handler(request: Request):
                from fastapi.responses import JSONResponse
                registry = {}
                for p in getattr(self, "_plugins", []):
                    registry[p.name] = list(getattr(p, "actions", {}).keys())
                return JSONResponse(registry)

            self.add_route("/basis/api/plugins-registry", _plugins_registry_handler, methods=["GET"], name="basis_plugins_registry")

    def _auto_discover_plugins(self):
        """
        Discover and register plugins from the local ``plugins/`` directory
        and from installed packages (via ``entry_points``).
        """
        # Layer 1: Local plugins/ directory (always — inherently app-scoped)
        for plugin in discover_local_plugins(self._app_dir, self._plugins_dir):
            self.include_plugin(plugin)

        # Layer 2: Installed plugins via entry_points (with optional filtering)
        if self._plugins_config is not False:
            allowlist = (
                self._plugins_config
                if isinstance(self._plugins_config, list)
                else None
            )
            for plugin in discover_installed_plugins(
                allowlist=allowlist, blocklist=self._exclude_plugins
            ):
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
        """
        if not hasattr(self, "_plugins"):
            self._plugins = []

        # Idempotent: skip if already registered (by identity or name)
        for existing in self._plugins:
            if existing is plugin or existing.name == plugin.name:
                logger.debug(f"Plugin '{plugin.name}' already registered, skipping.")
                return

        # 1. Wire all HTTP routes declared on the plugin's router.
        self.include_router(plugin.router)

        # 2. Serve static/component files so PyScript can load them.
        if plugin.static_dir and plugin.static_dir.exists():
            self.include_components_dir(
                plugin.static_mount,
                str(plugin.static_dir),
                name=plugin.name,
            )

        # 3. Optional SSR page.
        if hasattr(plugin, "root_component") and plugin.root_component:
            self.include_ssr_page(plugin.prefix or "/", plugin.root_component)

        # 4. Register the plugin's models into the app's models set.
        if not hasattr(self, "models"):
            self.models = set()
        if hasattr(plugin, "models"):
            self.models.update(plugin.models)

        # 5. Track included plugins
        self._plugins.append(plugin)

        # 6. Call on_register lifecycle hook
        try:
            plugin.on_register(self)
        except Exception as e:
            logger.error(f"\u274c Plugin '{plugin.name}' on_register failed: {e}")
            raise

    def entrypoint(self, component_cls=None, *, pyscript_src=ONLINE_PYSCRIPT):
        """
        Configure the app with bootstrap, component routes, and SSR page in one go.
        Returns the component class so it can be used as a decorator.
        """
        
        #handle optional argument case (i.e. @entrypoint decorator with no args)
        if component_cls is None:
            return functools.partial(self.entrypoint, pyscript_src=pyscript_src)


        self.bootstrap()

        # Detect where the component was defined to serve that directory
        try:
            component_file = Path(inspect.getfile(component_cls)).absolute()
        except (TypeError, OSError):
            # Fallback to the file that called entrypoint()
            caller_frame = inspect.stack()[1]
            component_file = Path(caller_frame.filename).absolute()
        
        app_dir = component_file.parent
        entry_module = f"/{component_file.name}"
        
        # Register the main SSR page
        self.include_ssr_page("/", component_cls, entry_module=entry_module, pyscript_src=pyscript_src)

        self.state.entry_module = entry_module
        self.state.pyscript_src = pyscript_src

        # Serve the application directory so PyScript can find the code
        self.include_components_dir("/", str(app_dir), name="app_root")

        return self

    def serve(self, component_cls, port=8000, **kwargs):
        """
        Bootstrap, register, and run a Basis app with HMR.
        """
        self.component(component_cls, **kwargs)

        # Print startup info
        import inspect
        from pathlib import Path
        try:
            component_file = Path(inspect.getfile(component_cls)).absolute()
        except:
            component_file = Path.cwd()

        print(f"\n🚀 Basis app starting at http://localhost:{port}")
        print(f"📦 Entry module: /{component_file.name}")
        print(f"🏠 App directory: {component_file.parent}\n")

        self.run_without_hmr(port=port)
        

class BasisAPIRouter(APIRouter):
    def component(self, cls):

        print(f"declaring {cls} is a component with a filename {cls.__file__}!")
        return cls
