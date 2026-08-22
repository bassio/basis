"""Bootstrap orchestration + conventional auto-discovery for the Basis server.

The boot-time wiring (``BootstrapMixin`` mixed into ``Basis``) plus the
conventional ``components/`` / ``stores/`` auto-discovery. Extracted from
``app.py`` so the app class stays a thin composition of focused mixins.
Plugin discovery lives in :mod:`basis.server.plugins`; the mount helpers
(``include_components_dir`` etc.) stay on ``Basis``.
"""
import importlib.util
import inspect
import logging
from pathlib import Path

from starlette.routing import Mount

from basis.server.plugins import _resolve_canonical_package
from basis.server.static import BasisStaticFiles
from basis.server.vfs import pyscript_json

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


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


class BootstrapMixin:
    """Boot orchestration + conventional-dir/store auto-discovery for ``Basis``.

    Hosts ``bootstrap`` and the boot-time route/mount registrations it runs
    (RPC endpoint, offline PyScript, ``/pyscript.json``, framework client/shared
    mounts, the ``basis.ui`` suite) plus conventional ``components/``/
    ``stores/`` auto-discovery. The host app provides (during construction)
    ``_app_dir``, ``_components_dir``, ``_stores_dir``, ``_discovered_dirs``,
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

    def include_offline_pyscript(self, mount_path: str = "/pyscript"):
        if self._has_route(name="pyscript") or self._has_route(path=mount_path):
            return
        pyscript_mount = Mount(mount_path, BasisStaticFiles(packages=[("basis", "static/pyscript")]), name="pyscript")
        self.routes.append(pyscript_mount)

    def include_pyscript_json(self, mount_path: str = "/pyscript.json"):
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

    def include_ui_components(self):
        if self._has_route(name="basis_ui") or self._has_route(path="/basis/ui/"):
            return

        spec = importlib.util.find_spec("basis.ui")

        ui_path = Path(spec.origin).parent

        static_cls = self._get_static_files_cls()
        ui_mount = Mount("/basis/ui/", static_cls(directory=ui_path), name='basis_ui')

        self.routes.append(ui_mount)
        self._component_routes.append(ui_mount)
        self.vfs.add_component_route("/basis/ui/", ui_path)

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
