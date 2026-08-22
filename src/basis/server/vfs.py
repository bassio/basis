"""Filesystem-mount → client VFS (PyScript import namespace) helpers.

Every place that serves a component directory and derives the client-side
import module name / VFS URL must use these helpers so the derivations can
never drift apart.

The isomorphism invariant (docs/04_components/importing-components.md): the
client VFS import name MUST equal the filesystem import name. These helpers
keep the mount path mirrored in the import namespace, which is what all three
environments (server imports, client VFS, IDEs) resolve against.
"""

import inspect
import itertools
import logging
import sys
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


def normalize_mount(mount_path: str) -> str:
    """Normalize a mount path to a leading ``/`` and no trailing ``/`` (root → ``""``)."""
    clean = mount_path
    if not clean.startswith("/"):
        clean = "/" + clean
    return clean.rstrip("/")


def mount_to_module_name(mount_path: str, rel_path: Path) -> str | None:
    """Translate *rel_path* (relative to the mounted dir) into its dotted client
    import module name.

    The mount path becomes the import prefix (``/jotter/components`` →
    ``jotter.components``) and the file's stem the tail, with ``__init__``
    popping the package segment. Returns ``None`` when there is nothing to
    translate (e.g. a bare ``__init__.py`` at the mount root).
    """
    parts = [p for p in normalize_mount(mount_path).split("/") if p]
    parts += [p for p in rel_path.with_suffix("").parts if p]
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def vfs_relative_url(mount_path: str, rel_path: Path) -> str:
    """Server-relative VFS URL for *rel_path* under *mount_path* (starts with ``./``)."""
    url = "." + normalize_mount(mount_path) + "/" + rel_path.as_posix()
    return url.replace("//", "/")


def companion_assets(module_file: Path) -> tuple[Path, Path]:
    """Return the (css, html) companion files owned by *module_file*.

    A package's ``__init__.py`` owns the package-named companions
    (``pkg/__init__.py`` → ``pkg.css`` / ``pkg.html``); a flat module owns its
    stem-named companions (``my_comp.py`` → ``my_comp.css`` / ``my_comp.html``).
    """
    if module_file.name == "__init__.py":
        base = module_file.parent / module_file.parent.name
    else:
        base = module_file
    return base.with_suffix(".css"), base.with_suffix(".html")


class VFSRegistry:
    """Live, app-owned builder of the PyScript client VFS manifest.

    ``Basis`` holds one instance (``app.vfs``) and mutates it as component and
    plugin directories are mounted and unmounted, so ``/pyscript.json`` always
    reflects the current mounts without a full rebuild.

    :attr:`files` is the ``{DOMAIN}`` / ``{COMPONENTS_DIR_i}``-templated file
    map served via ``/pyscript.json``; :attr:`client_modules` is the list of
    import modules available to the client; :attr:`vfs_to_server_module` is the
    reverse map the RPC layer uses to dispatch server actions.
    """

    def __init__(self, pyc_mode: bool = False):
        self.pyc_mode = pyc_mode
        #: ``{DOMAIN}`` / ``{COMPONENTS_DIR_i}``-templated file map for pyscript.json.
        self.files: dict[str, str] = {}
        #: Dotted import module names served to the PyScript client.
        self.client_modules: list[str] = []
        #: Reverse map: client VFS module name -> server module name (RPC dispatch).
        self.vfs_to_server_module: dict[str, str] = {}
        #: normalized mount -> (COMPONENTS_DIR index, absolute directory).
        self._dirs: dict[str, tuple[int, Path]] = {}
        #: normalized mount -> client module names it contributed (surgical removal).
        self._dir_modules: dict[str, set[str]] = {}
        #: Monotonic COMPONENTS_DIR index counter (indices are never reused).
        self._next_index = 1

    @property
    def py_ext(self) -> str:
        """Served Python extension: ``.pyc`` in pyc mode, else ``.py``."""
        return ".pyc" if self.pyc_mode else ".py"

    def add_framework_files(self) -> None:
        """Register the framework's own client + shared modules in the VFS."""
        files = self.files
        py_ext = self.py_ext

        # Client-side code (under /client). Entrypoint .py files are never
        # converted to .pyc.
        files["{DOMAIN}/basis/client/entrypoint.py"] = "./basis/client/entrypoint.py"
        for f_name in [
            "component.py",
            "plugin.py",
            "actions.py",
            "errors.py",
            "errors_component.py",
        ]:
            stem = Path(f_name).stem
            target = stem + py_ext
            files[f"{{DOMAIN}}/basis/client/{target}"] = f"./basis/client/{target}"
        files["{DOMAIN}/basis/client/component.js"] = "./basis/client/component.js"

        # Shared (isomorphic) code.
        for f_name in [
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
        ]:
            stem = Path(f_name).stem
            target = stem + py_ext
            files[f"{{DOMAIN}}/basis/shared/{target}"] = f"./basis/shared/{target}"

    def add_component_route(self, mount_path: str, directory) -> int | None:
        """Register one component/plugin dir; returns its ``COMPONENTS_DIR`` index.

        Idempotent per mount path — re-adding an existing mount is a no-op that
        returns the existing index. Assigns the next available index (never
        reused) so labels stay stable across a session.
        """
        clean_mount = normalize_mount(mount_path)
        existing = self._dirs.get(clean_mount)
        if existing is not None:
            return existing[0]

        directory = Path(directory).absolute()
        index = self._next_index
        self._next_index += 1
        self._dirs[clean_mount] = (index, directory)
        added_modules: set[str] = set()
        self._dir_modules[clean_mount] = added_modules

        cdir_n_label = "{" + f"COMPONENTS_DIR_{index}" + "}"

        # The mount-prefix entry is registered even if the dir is missing so the
        # label always resolves; the dir's files are walked only if it exists.
        self.files[cdir_n_label] = "{DOMAIN}" + clean_mount

        if not directory.exists():
            return index

        for f in itertools.chain(directory.glob("*.py"), directory.glob("**/*.py")):
            rel_py = f.relative_to(directory)
            # VFS file name carries the pyc extension in pyc mode.
            rel_vfs = rel_py.with_name(f.stem + self.py_ext if self.pyc_mode else f.name)

            # component_file uses '/' as path separator in the PyScript VFS.
            component_file = cdir_n_label + "/" + rel_vfs.as_posix()
            component_file = component_file.replace("//", "/")

            # Server-relative URL must always start with './' and use POSIX separators.
            self.files[component_file] = vfs_relative_url(clean_mount, rel_vfs)

            # Translate file path to Python import path (isomorphic: VFS == filesystem).
            vfs_module_path = mount_to_module_name(clean_mount, rel_vfs)
            if vfs_module_path is None:
                continue

            if vfs_module_path not in self.client_modules:
                self.client_modules.append(vfs_module_path)
            added_modules.add(vfs_module_path)

            for asset in companion_assets(f):
                if asset.exists():
                    rel_asset = rel_py.parent / asset.name
                    asset_file = cdir_n_label + "/" + rel_asset.as_posix()
                    asset_file = asset_file.replace("//", "/")
                    self.files[asset_file] = vfs_relative_url(clean_mount, rel_asset)

            # Resolve the server-side Python module path (VFS name -> import name).
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
                    self.vfs_to_server_module[vfs_module_path] = ".".join(server_parts)
                    break

        return index

    def remove_component_route(self, mount_path: str) -> bool:
        """Surgically remove a mount's entries from the manifest. Returns True if removed."""
        clean_mount = normalize_mount(mount_path)
        entry = self._dirs.pop(clean_mount, None)
        if entry is None:
            return False
        index, _ = entry
        cdir_n_label = "{" + f"COMPONENTS_DIR_{index}" + "}"
        prefix = cdir_n_label + "/"

        # 1. File-map entries: the mount label + everything under its prefix.
        for key in [k for k in self.files if k == cdir_n_label or k.startswith(prefix)]:
            del self.files[key]

        # 2. Client modules + reverse map contributed by this mount.
        for module_name in self._dir_modules.pop(clean_mount, ()):
            self.vfs_to_server_module.pop(module_name, None)
            if module_name in self.client_modules:
                self.client_modules.remove(module_name)

        return True

    def component_module_name(self, component) -> str | None:
        """Resolve *component*'s source file to its client VFS import module name.

        Returns ``None`` for dynamic / ``-c`` classes (no source file) or when the
        component is not served by any registered component mount. Used by
        ``@app.page`` / ``shared.page`` to detect whether a component is already
        covered by a mounted component dir (the isomorphism check).
        """
        try:
            component_module_file = Path(inspect.getfile(component))
        except (TypeError, OSError):
            # Dynamic / -c defined classes have no source file.
            return None
        if not component_module_file:
            return None
        for mount, (_index, directory) in self._dirs.items():
            if component_module_file.is_relative_to(directory):
                # The module file for that component lives under this mount's dir.
                rel = component_module_file.relative_to(directory)
                module_path = mount_to_module_name(mount, rel)
                if module_path:
                    return module_path
        return None

    def component_url(self, component_file: Path) -> str | None:
        """Return the VFS URL of *component_file* under the first mount containing it."""
        for mount, (_index, directory) in self._dirs.items():
            if component_file.is_relative_to(directory):
                clean_mount = normalize_mount(mount)
                rel = component_file.relative_to(directory).as_posix()
                return f"{clean_mount}/{rel}"
        return None

    def log_warnings(self) -> None:
        """Warn loudly on isomorphism violations (VFS module != server module).

        Only entries with a resolvable server module are comparable; files
        outside any sys.path package are covered by conventional-dir discovery.
        """
        for vfs_name, server_name in self.vfs_to_server_module.items():
            if vfs_name != server_name:
                logger.warning(
                    f"⚠️  Isomorphism violation: VFS module '{vfs_name}' maps to "
                    f"server module '{server_name}'. Component mount paths must "
                    f"reproduce the filesystem package path so client VFS, server "
                    f"and IDEs resolve the same import names."
                )

    def render_manifest(self, base_url: str) -> dict:
        """Render the ``/pyscript.json`` payload for *base_url* (``{DOMAIN}`` → URL)."""
        files = {"{DOMAIN}": base_url}
        for k, v in self.files.items():
            files[k.replace("{DOMAIN}", base_url)] = v
        return {
            "files": files,
            "interpreter": "pyscript/pyodide/pyodide.mjs",
            "client_modules": self.client_modules,
        }


async def pyscript_json(request: Request):
    """Serve ``/pyscript.json`` from the app's live VFS registry."""
    base_url = str(request.base_url).removesuffix("/")
    return JSONResponse(request.app.vfs.render_manifest(base_url))

