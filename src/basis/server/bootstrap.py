"""Bootstrap orchestration + conventional auto-discovery for the Basis server.

The boot-time wiring (``BootstrapMixin`` mixed into ``Basis``) plus the
conventional ``components/`` / ``stores/`` / ``plugins/`` auto-discovery.
Extracted from ``app.py`` so the app class stays a thin composition of focused
mixins. Plugin *discovery* lives in :mod:`basis.server.plugins`; the mount
helpers (``include_components_dir`` etc.) stay on ``Basis``.
"""
import importlib
import inspect
import logging
from pathlib import Path

from starlette.routing import Mount

from basis.server.plugins import _resolve_canonical_package


logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


def _discover_conventional_dirs(
    app_dir: Path,
    components_dir: str = "components",
    stores_dir: str = "stores",
    plugins_dir: str = "plugins",
) -> list[dict]:
    """
    Find conventional subdirectories under *app_dir* (``components/``,
    ``stores/``, ``plugins/``) that exist as proper Python packages.

    Isomorphism invariant: the mount path for a discovered dir reproduces its
    package path, so the client VFS import name equals the filesystem import
    name (and what IDEs resolve). A conventional dir is only discovered if it
    is a real package (has an ``__init__.py``); otherwise it is skipped with a
    warning — silently inventing a VFS-only namespace would break IDE parity.

    ``plugins/`` is mounted like the other two so local plugin files (flat
    modules and packages alike) are served once at their package path — a local
    plugin must NOT self-mount its ``serving_dir`` (a flat-file plugin would
    otherwise mount its whole parent ``plugins/`` dir and duplicate every
    sibling's VFS destination). Installed plugins live outside the app tree and
    keep their own package-dir serving mounts.
    """
    found = []
    for name, subdir in (
        ("components", components_dir),
        ("stores", stores_dir),
        ("plugins", plugins_dir),
    ):
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


def page_bootstrap(app, page_cls=None) -> dict:
    """Per-page ``basis.bootstrap`` manifest section.

    Computes the bootstrap injected into ``/pyscript.json`` under
    ``basis.bootstrap`` (read by the client via ``pyscript.config``): the
    app-global ``store_modules`` / ``headless_modules`` plus, when ``?url=<route>``
    resolves to *page_cls*, the page-specific ``page_stores`` / ``entrypoint``.

    Consumed only by ``basis.server.vfs.pyscript_json`` (which imports it
    lazily). ``_page_store_names`` is imported lazily too — a top-level import of
    ``basis.shared.page`` here would re-enter ``basis.server.app`` mid-import
    (shared.page -> shared.component -> server.app) and fail.
    """
    from basis.shared.page import _page_store_names

    bootstrap: dict = {}

    store_modules = getattr(app, "_discovered_store_modules", [])
    if store_modules:
        bootstrap["store_modules"] = list(store_modules)

    headless_modules = getattr(getattr(app, "vfs", None), "headless_modules", [])
    if headless_modules:
        bootstrap["headless_modules"] = list(headless_modules)

    if page_cls is not None:
        declared_stores = getattr(page_cls, "stores", None)
        if declared_stores:
            page_store_names = _page_store_names(declared_stores)
            if page_store_names:
                bootstrap["page_stores"] = page_store_names

        if not getattr(page_cls, "__synthesized__", False):
            module_file = app.vfs.component_module_name(page_cls)
            if module_file and module_file != "basis.shared.page":
                bootstrap["entrypoint"] = {page_cls.__name__: module_file}

    return bootstrap


def page_js_modules(page_cls) -> dict[str, str]:
    """Collect the JS modules needed by *page_cls*'s component tree.

    A static walk of the page root component's template blueprints: every
    custom-element tag that resolves to a registered ``@js_component`` class
    contributes its module (via ``__js_name__``/``__js_module__``). Hidden
    (if-bound) subtrees are included — the walk reflects the page's *declared*
    intent, so tab-hidden components still preload. Components contributed
    dynamically (regions, slots, ``#``-refs, loop items from a parent binding)
    are not statically visible and fall back to the client's lazy loader.
    """
    from basis.shared.component import Component

    root_component = getattr(page_cls, "root_component", None)
    if root_component is None:
        return {}

    seen: set[type] = set()
    modules: dict[str, str] = {}
    stack: list[type] = [root_component]

    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)

        if getattr(cls, "__js_component__", False):
            name = getattr(cls, "__js_name__", None)
            url = getattr(cls, "__js_module__", None)
            if name and url:
                modules[name] = url

        blueprint = getattr(cls, "__blueprint__", None)
        root_elem = blueprint.get("component") if blueprint else None
        if root_elem is None:
            continue
        for node in root_elem.descendants:
            tag = getattr(node, "tagName", None)
            if not tag or "-" not in tag:
                continue
            child_cls = Component._registry.get(tag.lower())
            if child_cls is not None:
                stack.append(child_cls)

    return modules


class BootstrapMixin:
    """Boot orchestration + conventional-dir/store auto-discovery for ``Basis``.

    Hosts ``bootstrap`` and the boot-time route/mount registrations it runs
    (RPC endpoint, offline PyScript, ``/pyscript.json``, framework
    client/shared mounts) plus conventional ``components/``/``stores/``/
    ``plugins/`` auto-discovery. The built-in UI component suite ships as the
    official ``ui`` plugin (``basis.plugins.ui``), registered through the
    standard ``basis.plugins`` entry point along with the other in-tree
    plugins. The host app provides (during
    construction) ``_app_dir``, ``_components_dir``, ``_stores_dir``,
    ``_plugins_dir``, ``_discovered_dirs``,
    ``_bootstrapped``, ``_component_routes`` and ``vfs``, plus ``include_store``
    and the plugin/region stores that :meth:`bootstrap` wires together. The
    ``basis.shared.*`` imports inside :meth:`bootstrap` are intentionally local
    (shared modules re-enter ``basis.server.app`` during app load).
    """

    def bootstrap(self, include_offline_pyscript=True):
        if getattr(self, "_bootstrapped", False):
            return
        self._bootstrapped = True
        self.include_offline_pyscript()
        self.include_pyscript_json()
        self.include_framework()
        self.include_server_actions()
        self.include_plugins_projection()

        # --- Auto-discover conventional directories (components/, stores/, plugins/) ---
        # Mounts them with package-derived paths (isomorphic VFS namespace) and
        # imports stores/ modules so their module-scope instances register.
        # plugins/ is mounted too so local plugin files are served once at their
        # package path (flat-file plugins must not self-mount their parent dir).
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

        # --- Auto-discover plugins ---
        # Official in-tree plugins (e.g. basis.plugins.regions — the $regions
        # store, <ui-region> and the region contribution API) are registered
        # through the standard basis.plugins entry-point mechanism, exactly like
        # third-party plugins ("everything is a plugin").
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

    def include_offline_pyscript(self, mount_path: str = "/pyscript"):
        from basis.server.static import BasisStaticFiles

        if self._has_route(name="pyscript") or self._has_route(path=mount_path):
            return
        pyscript_mount = Mount(mount_path, BasisStaticFiles(packages=[("basis", "static/pyscript")]), name="pyscript")
        self.routes.append(pyscript_mount)

    def include_pyscript_json(self, mount_path: str = "/pyscript.json"):
        from basis.server.vfs import pyscript_json

        if self._has_route(path=mount_path):
            return
        self.add_route(mount_path, pyscript_json, methods=['get'])

    def include_framework(self):
        static_cls = self._get_static_files_cls()

        if not self._has_route(name="basis_client"):
            client_mount = Mount("/basis/client", static_cls(packages=[('basis', 'client')]), name='basis_client')
            self.routes.append(client_mount)

        if not self._has_route(name="basis_shared"):
            shared_mount = Mount("/basis/shared", static_cls(packages=[('basis', 'shared')]), name='basis_shared')
            self.routes.append(shared_mount)

        # Raw vendored JS libraries for @js_component. Served as plain static
        # assets — not Python, so nothing is VFS-transformed. See
        # JS-COMPONENT-PLAN.md.
        if not self._has_route(name="basis_js"):
            js_mount = Mount("/basis/js", static_cls(packages=[('basis', 'static/js')]), name='basis_js')
            self.routes.append(js_mount)

    def _auto_discover_dirs(self):
        """
        Mount conventional subdirectories (``components/``, ``stores/``,
        ``plugins/``) with package-derived mount paths so the client VFS
        namespace equals the filesystem import namespace (isomorphism).
        Idempotent: an existing mount wins. A conventional dir is only
        discovered if it is a real Python package (has ``__init__.py``);
        otherwise it is skipped with a warning (see
        ``_discover_conventional_dirs``).
        """
        self._discovered_dirs = {}
        for cfg in _discover_conventional_dirs(
            self._app_dir,
            self._components_dir,
            self._stores_dir,
            self._plugins_dir,
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

        Returns the dotted module names, which the per-page manifest serves to
        the client under ``basis.bootstrap.store_modules`` so PyScript imports
        the same modules, creates the same instances and hydrates them from
        ``#basis-initial-state``.
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
