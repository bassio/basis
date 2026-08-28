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
from collections import defaultdict
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
        #: Synthetic headless module source: mount-relative ``.py`` path -> source.
        self.synthetic_files: dict[str, str] = {}
        #: Synthetic headless module name -> (normalized mount, ``.py`` rel path).
        self.synthetic_modules: dict[str, tuple[str, str]] = {}
        #: Dotted module names of promoted headless components (client pre-import).
        self.headless_modules: list[str] = []
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
            "serialization.py",
            "app_state.py",
            "cookie_store.py",
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

        # Headless components: bare ``*.html`` (± ``*.css``) with no owning ``.py``
        # are promoted to reactive Component subclasses (see HEADLESS-COMPONENTS-PLAN).
        self._register_headless_components(clean_mount, directory, cdir_n_label, added_modules)

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

        # 3. Synthetic headless modules served by this mount.
        for module_name, (owner_mount, rel_py) in list(self.synthetic_modules.items()):
            if owner_mount == clean_mount:
                self.synthetic_files.pop(rel_py, None)
                del self.synthetic_modules[module_name]
                if module_name in self.headless_modules:
                    self.headless_modules.remove(module_name)

        return True

    def _register_headless_components(
        self,
        clean_mount: str,
        directory: Path,
        cdir_n_label: str,
        added_modules: set[str],
    ) -> None:
        """Detect headless ``*.html`` (no owning ``.py``) and promote them.

        Flat-only in v1: only ``*.html`` at the mount root are promoted, so the
        synthetic module keeps the flat ``{pkg}.{stem}`` import name that matches
        where a future ``{stem}.py`` would live. Nested ownerless ``.html`` files
        are left as ordinary assets with a debug note.

        Each promotion: builds + registers the server-side headless class,
        serves a synthetic client module from the static handler (pyc-style),
        and advertises it in the manifest under the module name a future real
        ``.py`` would use — so graduation is a pure manifest swap.
        """
        from basis.server.headless import (
            build_headless_module_source,
            create_headless_component,
            headless_identity,
        )

        owned: dict[Path, set[str]] = defaultdict(set)
        for py in itertools.chain(directory.glob("*.py"), directory.glob("**/*.py")):
            if "__pycache__" in py.parts:
                continue
            owned[py.parent].add(py.parent.name if py.name == "__init__.py" else py.stem)

        mount_pkg = ".".join(p for p in clean_mount.split("/") if p)

        for html in directory.glob("*.html"):  # flat-only (v1)
            stem = html.stem
            if stem.startswith("_"):
                continue
            if stem in owned.get(directory, ()):
                continue  # owned by a real .py
            css = html.with_suffix(".css")
            cls_name, tag, module_name = headless_identity(mount_pkg, stem)

            try:
                template = html.read_text(encoding="utf-8")
                style = css.read_text(encoding="utf-8") if css.exists() else ""
            except OSError:
                logger.warning(f"⚠️  Headless component '{html.name}' unreadable; skipping")
                continue

            cls = create_headless_component(cls_name, tag, template, style, module_name)
            if cls is None:
                logger.warning(
                    f"⚠️  Skipping headless component '{html.name}': tag '{tag}' is "
                    f"already owned by a real component, or the template is empty."
                )
                continue

            # Serve the synthetic module from the static handler (pyc-style) and
            # advertise it in the manifest under the module a future .py would use.
            rel_py = Path(f"{stem}.py")
            rel_vfs = rel_py.with_name(stem + self.py_ext)  # .py or .pyc
            component_file = cdir_n_label + "/" + rel_vfs.as_posix()
            self.files[component_file] = vfs_relative_url(clean_mount, rel_vfs)

            if module_name not in self.client_modules:
                self.client_modules.append(module_name)
            added_modules.add(module_name)
            if module_name not in self.headless_modules:
                self.headless_modules.append(module_name)

            source = build_headless_module_source(cls_name, tag, template, style)
            self.synthetic_files[rel_py.as_posix()] = source
            self.synthetic_modules[module_name] = (clean_mount, rel_py.as_posix())

            # List the real .html/.css so they are fetchable / visible in the
            # manifest (mirrors how .py companions are listed).
            for asset in (html, css):
                if asset.exists():
                    rel_asset = asset.relative_to(directory)
                    self.files[cdir_n_label + "/" + rel_asset.as_posix()] = \
                        vfs_relative_url(clean_mount, rel_asset)

            logger.info(
                f"🧩 Headless component: '{html.name}' → <{tag}> "
                f"(class {cls_name}, module {module_name}). "
                f"Add {stem}.py to graduate."
            )

        # Debug-note nested ownerless .html (not promoted in v1 — flat-only).
        for html in directory.glob("**/*.html"):
            if html.parent == directory:
                continue
            if html.stem.startswith("_") or "__pycache__" in html.parts:
                continue
            if html.stem in owned.get(html.parent, ()):
                continue
            logger.debug(
                f"Headless component in a subfolder is not promoted yet "
                f"(v1 is flat-only): {html.relative_to(directory)}"
            )

    def regenerate_headless_source(self, mount_path: str, rel_py: str) -> bool:
        """Re-read a headless component's ``.html``/``.css`` and regenerate its
        served synthetic module (keeps hard-refreshes fresh after dev edits).

        Also refreshes the live server-side class so the next SSR first-paint
        reflects the edit. Returns True when the source was regenerated.
        """
        from basis.server.headless import (
            build_headless_module_source,
            headless_identity,
            refresh_headless_class,
        )
        from basis.shared.base_component import BaseComponent

        clean_mount = normalize_mount(mount_path)
        entry = self._dirs.get(clean_mount)
        if entry is None:
            return False
        _, directory = entry
        rel_py_path = Path(rel_py)
        html = directory / rel_py_path.with_suffix(".html")
        if not html.exists():
            return False
        css = html.with_suffix(".css")
        stem = rel_py_path.stem
        mount_pkg = ".".join(p for p in clean_mount.split("/") if p)
        cls_name, tag, module_name = headless_identity(mount_pkg, stem)

        try:
            template = html.read_text(encoding="utf-8")
            style = css.read_text(encoding="utf-8") if css.exists() else ""
        except OSError:
            return False

        # 1. Served source (next page load is fresh).
        self.synthetic_files[rel_py_path.as_posix()] = build_headless_module_source(
            cls_name, tag, template, style
        )

        # 2. Live server-side class (next SSR first-paint is fresh).
        cls = BaseComponent._registry.get(tag)
        if cls is not None and getattr(cls, "__headless__", False):
            refresh_headless_class(cls, template, style)

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

    def render_manifest(self, base_url: str, bootstrap: dict | None = None) -> dict:
        """Render the ``/pyscript.json`` payload for *base_url* (``{DOMAIN}`` → URL).

        *bootstrap* is the per-page ``basis.bootstrap`` section computed by
        :func:`basis.server.bootstrap.page_bootstrap` (``None`` for a bare
        fetch). The ``basis.bootstrap`` key is always present (possibly empty) so
        the client can rely on it.
        """
        files = {"{DOMAIN}": base_url}
        for k, v in self.files.items():
            files[k.replace("{DOMAIN}", base_url)] = v
        return {
            "files": files,
            "interpreter": "pyscript/pyodide/pyodide.mjs",
            "client_modules": self.client_modules,
            "basis": {"bootstrap": bootstrap or {}},
        }


async def pyscript_json(request: Request):
    """Serve ``/pyscript.json`` from the app's live VFS registry.

    Page-aware: ``?url=<route>`` selects a registered page whose page-specific
    bootstrap (``entrypoint``, ``page_stores``) is injected under
    ``basis.bootstrap`` alongside the app-global ``store_modules`` /
    ``headless_modules``. Bare fetches (no ``?url=``) get app-global only.
    """
    from basis.server.bootstrap import page_bootstrap

    base_url = str(request.base_url).removesuffix("/")
    page_cls = None
    url = request.query_params.get("url")
    if url is not None:
        page_cls = request.app._pages.get(url)
    bootstrap = page_bootstrap(request.app, page_cls)
    return JSONResponse(request.app.vfs.render_manifest(base_url, bootstrap=bootstrap))

