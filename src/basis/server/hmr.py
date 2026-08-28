"""Hot Module Replacement (HMR) support for the Basis server.

The WebSocket connection manager, the component file-watcher and the
``uvicorn`` runners that power live client reloads. Extracted from
``app.py`` into an ``HMRMixin`` so the ``Basis`` class stays a thin
composition of focused mixins.
"""
import asyncio
import itertools
import logging
from pathlib import Path
from typing import Set

from fastapi import WebSocket, WebSocketDisconnect

from basis.server.vfs import companion_assets, mount_to_module_name

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


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


class HMRMixin:
    """File-watcher, WebSocket endpoint and runner methods for ``Basis``.

    The host app is expected to provide, during construction:

    * ``self._start_hmr_watcher`` — whether the poller should run on startup.
    * ``self._hmr_map_dirty`` — set to ``True`` whenever a component mount or
      plugin set changes so the watcher rebuilds its file map.
    * ``self._component_routes`` — the mounted component dirs to watch.

    ``hmr_manager`` is a class-level connection manager shared by every
    ``Basis`` instance (it was historically a class attribute on ``Basis``).
    """

    hmr_manager = HMRManager()

    def _build_hmr_file_map(self):
        """
        Build ``{absolute_path: meta}`` for every watched component file.

        Every entry carries the authoritative client **import module name** of the
        component that owns it (same derivation as the VFS manifest —
        ``basis.server.vfs.VFSRegistry``):

        * ``.py`` files map to their own module (``jotter.components.statusbar``).
        * ``.css`` / ``.html`` companion files map to the module that loads them
          (package ``titlebar/__init__.py`` -> ``titlebar/titlebar.css``, or a
          flat ``my_comp.py`` -> ``my_comp.css``).

        The client uses this to find the component class by ``__module__`` instead
        of guessing a class name from the filename (which breaks for names like
        ``titlebar.css`` -> class ``TitleBar``).
        """
        file_map = {}
        for m in self._component_routes:
            watch_dir = Path(m.app.directory).absolute()
            if not watch_dir.exists():
                continue

            # Map each .py module file to its import name, and its companion
            # css/html assets to the same module (mirrors initialize_pyscript_registry).
            asset_owners = {}
            for f in watch_dir.rglob("*.py"):
                if "__pycache__" in f.parts:
                    continue
                module_name = mount_to_module_name(m.path, f.relative_to(watch_dir))
                if module_name is None:
                    continue
                for asset in companion_assets(f):
                    if asset.exists():
                        asset_owners[str(asset.absolute())] = module_name

            # Headless assets: a .html/.css with no .py owner belongs to its
            # synthetic headless module (mirrors VFSRegistry promotion), so HMR
            # edits hot-swap the right class (matched by __module__).
            for rel_py in getattr(self.vfs, "synthetic_files", {}):
                module_name = mount_to_module_name(m.path, Path(rel_py))
                if module_name is None:
                    continue
                for asset in companion_assets(watch_dir / rel_py):
                    if asset.exists():
                        asset_owners[str(asset.absolute())] = module_name

            for f in itertools.chain(watch_dir.rglob("*.py"), watch_dir.rglob("*.html"), watch_dir.rglob("*.css")):
                # Never watch compiled bytecode or stray caches
                if "__pycache__" in f.parts or f.suffix == ".pyc":
                    continue
                rel = f.relative_to(watch_dir)
                meta = {"file": str(rel), "ext": f.suffix.lstrip(".")}
                if f.suffix == ".py":
                    module_name = mount_to_module_name(m.path, rel)
                    if module_name is not None:
                        meta["module"] = module_name
                else:
                    meta["module"] = asset_owners.get(str(f.absolute()))
                file_map[str(f.absolute())] = meta
        return file_map

    async def _start_file_watcher(self):
        """Simple poller to watch for file changes and broadcast HMR events.

        Watch dirs are re-derived from the current component mounts each cycle,
        and the file map is rebuilt when ``_hmr_map_dirty`` is set (a plugin was
        added or removed), so live plugin enable/disable stays in sync with HMR.
        """
        mtimes = {}
        file_map = self._build_hmr_file_map()
        self._hmr_map_dirty = False

        while True:
            try:
                if self._hmr_map_dirty:
                    file_map = self._build_hmr_file_map()
                    self._hmr_map_dirty = False
                watch_dirs = [Path(m.app.directory).absolute() for m in self._component_routes]
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
                            # Headless component edit: regenerate the served
                            # synthetic source so the next hard-refresh (and SSR
                            # first-paint) is fresh — mirror of the pyc mtime cache.
                            if meta.get("ext") in ("html", "css"):
                                mod = meta.get("module")
                                if mod:
                                    syn = getattr(self.vfs, "synthetic_modules", {})
                                    if mod in syn:
                                        _mount, rel_py = syn[mod]
                                        self.vfs.regenerate_headless_source(_mount, rel_py)
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

    async def hmr_websocket_endpoint(self, websocket: WebSocket):
        await self.hmr_manager.connect(websocket)
        try:
            while True:
                await websocket.receive_text()  # Just keep connection alive
        except WebSocketDisconnect:
            self.hmr_manager.disconnect(websocket)
        except Exception:
            self.hmr_manager.disconnect(websocket)
