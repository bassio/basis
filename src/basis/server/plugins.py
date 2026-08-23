"""Plugin subsystem for the Basis server.

Discovery (local ``plugins/`` dir + installed ``entry_points``), dependency
ordering, the app-side registration record, and the plugin lifecycle methods
mixed into :class:`basis.server.app.Basis` via ``PluginMixin``.

Extracted from ``app.py`` so the app class stays a thin composition of focused
mixins. Note the sibling module :mod:`basis.server.plugin` holds the
``BasisPlugin`` class itself; this module is the *subsystem* around it.
"""
import importlib
import importlib.util
import inspect
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from basis.server.ast_utils import collect_imported_modules
from basis.server.plugin import BasisPlugin
from basis.server.vfs import mount_to_module_name

logger = logging.getLogger('uvicorn.error')
logger.setLevel(logging.DEBUG)


# Framework-essential plugins: effectively core primitives that would strand an
# app if unloaded (e.g. `regions` provides <ui-region> / $regions). remove_plugin
# / disable_plugin refuse to unload these unless force=True — the plugin manager
# must not be able to break a page that depends on them.
FRAMEWORK_PLUGIN_NAMES = ("regions",)


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
    store_items: list = field(default_factory=list)
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


class PluginMixin:
    """Plugin lifecycle + discovery methods mixed into :class:`~basis.server.app.Basis`.

    The host app provides (during construction) the plugin configuration state
    (``_plugins``, ``_plugin_registrations``, ``_plugins_dir``, ``_plugins_config``,
    ``_exclude_plugins``, ``_app_dir``) plus the shared app surface the lifecycle
    wires into: ``include_components_dir``, ``include_page``, ``_has_route``,
    ``routes``, ``_component_routes`` and the ``$plugins`` store.

    ``include_plugin`` imports ``_synthesize_page`` from
    :mod:`basis.shared.page` via a local import to avoid a circular import at
    module load (the mixin runs on the fully-imported ``Basis`` instance). The
    PyScript VFS manifest is maintained by the app-owned
    :class:`~basis.server.vfs.VFSRegistry` instance (``app.vfs``), so the plugin
    lifecycle has no dependency on ``app.py``.
    """

    def include_plugins_projection(self, mount_path: str = "/basis/api/plugins"):
        """Register the ``$plugins`` listing endpoint (``GET /basis/api/plugins``)."""
        if self._has_route(path=mount_path):
            return

        async def _plugins_projection_handler(request):
            from fastapi.responses import JSONResponse
            from basis.shared.plugin_registry import _plugin_listing
            return JSONResponse(_plugin_listing(self))

        self.add_route(mount_path, _plugins_projection_handler, methods=["GET"], name="basis_plugins_projection")

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
            from basis.shared.page import _synthesize_page  # local: shared.page re-enters basis.server.app during load
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
        from basis.plugins.regions.registry import _register_contribution
        plugin._app = self
        pending = list(getattr(plugin, "_region_items", []) or [])
        reg.region_items = list(pending)
        for contrib in pending:
            # Lazily initialize the app-owned insertion counter: the regions
            # plugin normally owns it, but a contributing plugin may be included
            # before the regions plugin registers.
            contrib.seq = getattr(self, "_region_seq", 0)
            self._region_seq = contrib.seq + 1
            _register_contribution(self, contrib)

        # 6c. Stores declared by the plugin (@plugin.store / include_store) are
        #     wired into the app: constructed/blueprinted, app-attached (if
        #     _requires_app), and added to the app-global store list. Recorded
        #     on the registration so remove/disable can unwind them.
        pending_stores = list(getattr(plugin, "_store_items", []) or [])
        reg.store_items = list(pending_stores)
        for store_name, store_cls in pending_stores:
            plugin.include_store(self, store_cls, store_name)

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

    def _after_plugin_change(self):
        """Post-registration bookkeeping shared by include/remove/enable_plugin.

        The client VFS manifest is maintained incrementally by the app's
        ``VFSRegistry`` (add/remove_component_route) as mounts change; this
        re-derives the HMR file map, the ``$plugins`` projection and the
        plugin→importers cache so they match the current plugin set.
        """
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

        Reverts the plugin's routes, component mount (from the app route list,
        ``_component_routes`` and the live VFS registry — a surgical manifest
        prune), models, and its action surface (``_plugins``), re-derives the
        HMR file map, resets the OpenAPI cache, and runs the plugin's
        ``on_shutdown`` hook. The plugin object is kept (as a disposed
        registration) so :meth:`enable_plugin` can re-register it later.

        Refuses (returns ``False``) when the plugin is imported by a client
        module directly — unloading it would prune the client VFS and break the
        next page load. Pass ``force=True`` to override (the client bundle will
        then fail to import the plugin on the next load).

        Framework-essential plugins (``FRAMEWORK_PLUGIN_NAMES`` — currently
        ``regions``) are always refused unless ``force=True``: they provide core
        primitives (``<ui-region>`` / ``$regions``) that a page may depend on.

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
            if name in FRAMEWORK_PLUGIN_NAMES:
                logger.warning(
                    f"⚠️  Plugin '{name}' is a framework-essential plugin "
                    f"(provides core primitives like <ui-region>) — refusing "
                    f"to unload. Pass force=True to override."
                )
                return False
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

        # 2. Component mount — lives in the app route list, _component_routes and
        #    the app's live VFS registry (surgical manifest prune).
        if reg.component_mount is not None:
            try:
                self.routes.remove(reg.component_mount)
            except ValueError:
                pass
            try:
                self._component_routes.remove(reg.component_mount)
            except ValueError:
                pass
            self.vfs.remove_component_route(reg.component_mount.path)

        # 3. Models contributed by the plugin.
        if hasattr(self, "models") and reg.models:
            self.models -= reg.models

        # 3b. Region contributions contributed by the plugin.
        if getattr(reg, "region_items", None):
            from basis.plugins.regions.registry import _unregister_contribution
            for contrib in reg.region_items:
                _unregister_contribution(self, contrib)
            reg.region_items = []

        # 3c. Stores contributed by the plugin (@plugin.store / include_store):
        #     drop them from the app-global store list and the live registry so
        #     they stop being collected/serialized. The persistent store
        #     blueprint is intentionally kept (full teardown is a Phase-4
        #     decision — disabling a store-providing plugin is otherwise
        #     half-hearted until then).
        if getattr(reg, "store_items", None):
            from basis.shared.store import Store
            for store_name, _store_cls in reg.store_items:
                self._global_stores[:] = [
                    c for c in self._global_stores if c.get("name") != store_name
                ]
                Store._registry.pop(store_name, None)
            reg.store_items = []

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

        # 6. Lifecycle teardown, then post-removal bookkeeping (HMR map +
        #    $plugins projection + importer cache).
        try:
            await reg.plugin.on_shutdown(self)
        except Exception as e:
            logger.warning(f"⚠️  Plugin '{name}' on_shutdown failed during remove: {e}")

        self._after_plugin_change()
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
        # include_plugin re-mounts the static dir, re-adding its entries to the
        # app's live VFS registry (mirroring remove_plugin's surgical prune), so
        # the client can import the plugin's modules on the next page load.
        self._after_plugin_change()
        try:
            await plugin.on_startup(self)
        except Exception as e:
            logger.warning(f"⚠️  Plugin '{name}' on_startup failed after re-enable: {e}")
        return True
