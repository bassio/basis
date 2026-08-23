import asyncio
import functools
import inspect
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager
from starlette.routing import Mount
from basis.server.static import BasisStaticFiles, BasisStaticFilesPyc
from basis.server.vfs import VFSRegistry
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse

from basis.server.db import DBAppMixin
from basis.server.hmr import HMRManager, HMRMixin
from basis.server.plugins import (
    PluginMixin,
    PluginRegistration,
    _topo_sort_plugins,
    discover_installed_plugins,
    discover_local_plugins,
)
from basis.server.bootstrap import BootstrapMixin


ONLINE_PYSCRIPT = "https://pyscript.net/releases/2026.3.1"

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


class Basis(FastAPI, DBAppMixin, HMRMixin, PluginMixin, BootstrapMixin):
    
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
        # Instance-level mount/store registries (no class-level sharing).
        self._component_routes = []
        self._component_dirs = []
        self._global_stores = []
        # Live PyScript VFS manifest — owned by this app, mutated as dirs mount.
        self.vfs = VFSRegistry(self.pyc_mode)
        self.vfs.add_framework_files()
        if not hasattr(self, "_plugins"):
            self._plugins = []
        # Revertible plugin registration records (teardown truth, keyed by name).
        self._plugin_registrations = {}
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
            
            # Surface isomorphism violations at boot (the VFS manifest is built
            # incrementally as component/plugin dirs are mounted).
            app.vfs.log_warnings()
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

    def _has_route(self, *, path: str | None = None, name: str | None = None) -> bool:
        """True if a route already matches the given path and/or name."""
        for r in self.routes:
            if path is not None and getattr(r, "path", None) == path:
                return True
            if name is not None and getattr(r, "name", None) == name:
                return True
        return False

    def _get_static_files_cls(self):
        return BasisStaticFilesPyc if getattr(self, "pyc_mode", False) else BasisStaticFiles

    def include_components_dir(self, mount_path: str, dir_path: str, name: str):
        if any(getattr(r, "path", None) == mount_path for r in self._component_routes):
            return None

        static_cls = self._get_static_files_cls()
        m = Mount(mount_path, static_cls(directory=dir_path), name=name)

        self.routes.append(m)
        self._component_routes.append(m)
        self.vfs.add_component_route(mount_path, dir_path)
        self._invalidate_plugin_importers()
        return m

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

        from basis.shared.page import _synthesize_page, Page as PageBase

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
        covered_module = self.vfs.component_module_name(component_cls)
        if covered_module:
            entry_module = self.vfs.component_url(component_file)
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
