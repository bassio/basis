import keyword
from pathlib import Path
from typing import Any

from fastapi import APIRouter
from basis.server.db import ModelRegistryMixin


def _is_valid_plugin_name(name: str) -> bool:
    """A plugin name must be a valid Python identifier (the $plugins.<name> DSL key
    and the client proxy attribute), so no spaces, hyphens, leading digits, or
    Python keywords."""
    return name.isidentifier() and not keyword.iskeyword(name)


def _sanitize_plugin_name(value: str) -> str:
    """Derive a valid Python identifier from a prefix-derived default name."""
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)
    if not out:
        out = "plugin"
    if out[0].isdigit():
        out = "_" + out
    if keyword.iskeyword(out):
        out += "_"
    return out


def _resolve_plugin_name(name: str | None, prefix: str) -> str:
    """Validate an explicit plugin name or sanitize the prefix-derived default.

    An explicit invalid ``name=`` is a loud error (author intent); a derived
    default is sanitized so it cannot silently break ``$plugins.<name>``.
    """
    if name is not None:
        if not _is_valid_plugin_name(name):
            raise ValueError(
                f"Plugin name {name!r} must be a valid Python identifier "
                f"(no spaces, hyphens, or leading digits, and not a Python "
                f"keyword) — it is used as $plugins.<name> and the client "
                f"proxy attribute. Pass an explicit name= or use a prefix "
                f"that is a valid identifier."
            )
        return name
    return _sanitize_plugin_name(prefix.strip("/").replace("/", "_") or "plugin")


class BasisPlugin(ModelRegistryMixin):
    #: Contribution classification — ``"plugin"`` (default) or ``"theme"``.
    #: A generic partition key (ROADMAP-THEMING.md §6.5.1): the plugin/theme
    #: managers are the same registry under different kind filters, and themes
    #: never appear in the plugin manager. Core never interprets the value.
    kind: str = "plugin"

    """
    A self-contained, route-aware bundle that can be registered into a Basis
    app via ``app.include_plugin(plugin)`` or auto-discovered from the
    ``plugins/`` directory or installed packages.

    A plugin declares:
    - A URL prefix for its HTTP routes (``prefix``).
    - An optional directory of Python/HTML/CSS component files to serve to the
      client so PyScript can import them (``serving_dir`` / ``serving_mount``).
    - An optional list of plugin names it depends on (``requires``).
    - Any number of REST endpoints via ``@plugin.get``, ``@plugin.post``, etc.
      (or directly via ``@plugin.router.get`` for full FastAPI expressiveness).
    - Server actions via the bare ``@server_action`` decorator (unchanged) —
      these self-register in the global ``_action_registry`` on import and are
      reached by clients through the global ``POST /basis/api/action`` endpoint.

    Auto-Discovery
    --------------
    Plugins can be auto-discovered without manual ``include_plugin()`` calls:

    1. **Local**: Place a Python file or package in your app's ``plugins/``
       directory. It must expose a module-level ``plugin`` variable that is a
       ``BasisPlugin`` instance.
    2. **Installed**: Publish a package with a ``basis.plugins`` entry point
       in ``pyproject.toml``.

    Example
    -------
    ::

        # my_chat/__init__.py
        from pathlib import Path
        from basis.server.plugin import BasisPlugin
        from basis.shared.actions import server_action

        plugin = BasisPlugin(
            prefix="/chat",
            serving_dir=Path(__file__).parent,
            serving_mount="/chat",
        )

        @server_action
        async def send_message(session_id: str, text: str) -> dict:
            ...

        @plugin.get("/history")
        async def chat_history(request):
            ...

        # Equivalent using the router directly (full FastAPI expressiveness):
        @plugin.router.get("/stats", response_model=dict)
        async def stats():
            ...

        # Exposing a model:
        @plugin.expose("/messages/", one=False)
        class Message(SQLModel, table=True):
            id: int | None = Field(default=None, primary_key=True)
            text: str

    ::

        # app.py — auto-discovery (plugins/ directory)
        from basis import Basis

        app = Basis(plugins_dir="plugins")  # discovers & registers automatically

        # Or explicit registration:
        from my_chat import plugin as chat_plugin
        app.include_plugin(chat_plugin)
    """

    def __init__(
        self,
        *,
        prefix: str,
        serving_dir: str | Path | None = None,
        serving_mount: str | None = None,
        name: str | None = None,
        tags: list[str] | None = None,
        requires: list[str] | None = None,
    ):
        """
        Parameters
        ----------
        prefix:
            URL prefix applied to all routes declared on this plugin's router
            (e.g. ``"/chat"``).  Leading slash is required; trailing slash is
            stripped automatically.
        serving_dir:
            Filesystem path to the directory served to the client (its .py files
            become client-importable modules; any css/fonts inside are served
            too).  When provided the whole dir is mounted at ``serving_mount``.
        serving_mount:
            URL path at which ``serving_dir`` is mounted.  Defaults to
            ``prefix`` when not supplied.
        name:
            Optional human-readable identifier used when registering the static
            mount.  Defaults to a sanitised version of ``prefix``.
        tags:
            OpenAPI tags applied to all routes on this plugin's router.
        requires:
            List of plugin names this plugin depends on.  Used for ordering
            plugin registration (dependency-based topological sort in later
            phases).  Does not affect installation — use Python package
            dependencies for that.
        """
        self.prefix = prefix.rstrip("/")
        self.serving_dir = Path(serving_dir) if serving_dir else None
        self.serving_mount = serving_mount or self.prefix
        self.name = _resolve_plugin_name(name, self.prefix)
        self.requires = requires or []
        self.models = set()
        self.actions = {}
        # canonical path (module.qualname) -> action wrapper, for unwinding the
        # global action registry on remove/disable (revertible registration).
        self._action_registry_entries = {}
        self._settings = {}
        # Region contributions declared via add_to_region / @plugin.region. Flushed
        # into the app registry by include_plugin (ROADMAP-SPATIAL.md A1).
        self._region_items = []
        # Stores declared via include_store / @plugin.store. Wired into the app
        # by include_plugin (and recorded on PluginRegistration for unwind).
        self._store_items = []
        self._app = None
        # Public router — use @plugin.router.get(...) for full FastAPI control,
        # or the convenience shorthands below.
        self.router = APIRouter(prefix=self.prefix, tags=tags or [])

    def action(self, func_or_name: Any = None, name: str | None = None) -> Any:
        """
        Decorator to register a server action scoped to this plugin.
        Can be used as:

        @plugin.action
        def my_action(): ...

        or

        @plugin.action(name="custom_name")
        def my_action(): ...
        """
        from functools import wraps

        def decorator(func):
            action_name = name
            if not action_name and isinstance(func_or_name, str):
                action_name = func_or_name
            if not action_name:
                action_name = func.__name__

            @wraps(func)
            async def wrapper(*args, **kwargs):
                import asyncio
                if asyncio.iscoroutinefunction(func):
                    return await func(*args, **kwargs)
                else:
                    return func(*args, **kwargs)

            self.actions[action_name] = wrapper
            # Expose the action as an attribute so the documented direct-import
            # form (`await plugin.<action>(...)`) works on the plugin object too.
            setattr(self, action_name, wrapper)

            # Register under the canonical path (module.qualname — the same rule
            # as @server_action) so the single RPC endpoint dispatches plugin
            # actions by path alone. Tracked on the plugin so include/remove can
            # unwind the global registry entry.
            from basis.shared.actions import _action_registry
            canonical_path = f"{func.__module__}.{func.__qualname__}"
            self._action_registry_entries[canonical_path] = wrapper
            _action_registry[canonical_path] = wrapper
            return wrapper

        if callable(func_or_name):
            return decorator(func_or_name)
        return decorator

    def add_to_region(self, region, component_cls, *, props=None, order=None, position="end"):
        """Register *component_cls* into *region* (ROADMAP-SPATIAL.md A1).

        Returns a ``RegionHandle`` disposer. Class-as-identity: re-adding the
        same class to the same region replaces the existing entry (HMR-safe).
        Contributions declared at module scope / ``on_register`` are flushed
        into the app registry by ``include_plugin`` (and recorded on the
        ``PluginRegistration`` so disable/remove unwind them); if the plugin is
        already registered they register immediately.
        """
        from basis.plugins.regions.registry import (
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
            owner=self.name,
        )
        if not hasattr(self, "_region_items"):
            self._region_items = []
        self._region_items.append(contrib)
        app = getattr(self, "_app", None)
        if app is not None:
            _register_contribution(app, contrib)
        return RegionHandle(contrib, app=app, owner=self)

    def region(self, name, **kwargs):
        """Decorator form of :meth:`add_to_region` — declare a class as a region
        item (the plugin's voice, like ``@plugin.action`` / ``@plugin.get``)."""
        def decorator(cls):
            self.add_to_region(name, cls, **kwargs)
            return cls
        return decorator

    def store(self, func_or_name=None, name=None):
        """Decorator: declare a store class this plugin provides (wired on include).

        Usable as ``@plugin.store`` (the store class's own default constructor
        name is used, e.g. ``RegionStore()`` → ``"regions"``), as
        ``@plugin.store("name")``, or as ``@plugin.store(name="name")``.
        """
        if name is None and isinstance(func_or_name, str):
            name = func_or_name

        def decorator(cls):
            self._store_items.append((name, cls))
            return cls

        if callable(func_or_name):
            return decorator(func_or_name)
        return decorator

    def include_store(self, app, store_cls, name=None):
        """Wire a store this plugin provides into *app* (first-class store API).

        Constructs/reuses the store (blueprint-aware), registers it in the app's
        store registry, app-attaches it if it opts in via ``_requires_app`` (e.g.
        ``$regions``), and adds it to the app's global store list so SSR/CSR
        collect it. Returns the wired instance.

        Used by a plugin's ``on_register`` (the app is available there) and by
        ``include_plugin`` for stores declared with :meth:`store`.
        """
        from basis.shared.store import Store, attach_app_to_store

        if name is None:
            instance = store_cls()
            name = instance.get_store_name()
        else:
            instance = (
                Store._registry.get(name)
                or Store.reinstantiate(name)
                or store_cls(name)
            )
        Store._registry[name] = instance
        attach_app_to_store(instance, app)
        app.include_store(name)
        # Record as a plugin-provided store so include/remove can unwind it.
        item = (name, store_cls)
        if item not in self._store_items:
            self._store_items.append(item)
        return instance

    # ------------------------------------------------------------------
    # Convenience aliases — delegate to self.router so callers can write
    # @plugin.get("/path") instead of @plugin.router.get("/path").
    # ------------------------------------------------------------------

    def get(self, path: str, **kwargs):
        """Shorthand for ``@plugin.router.get(path, ...)``."""
        return self.router.get(path, **kwargs)

    def post(self, path: str, **kwargs):
        """Shorthand for ``@plugin.router.post(path, ...)``."""
        return self.router.post(path, **kwargs)

    def put(self, path: str, **kwargs):
        """Shorthand for ``@plugin.router.put(path, ...)``."""
        return self.router.put(path, **kwargs)

    def delete(self, path: str, **kwargs):
        """Shorthand for ``@plugin.router.delete(path, ...)``."""
        return self.router.delete(path, **kwargs)

    def patch(self, path: str, **kwargs):
        """Shorthand for ``@plugin.router.patch(path, ...)``."""
        return self.router.patch(path, **kwargs)

    def __repr__(self) -> str:
        return (
            f"BasisPlugin(prefix={self.prefix!r}, "
            f"serving_mount={self.serving_mount!r}, "
            f"name={self.name!r})"
        )

    # ------------------------------------------------------------------
    # Lifecycle hooks — override in subclasses for custom behaviour.
    # ------------------------------------------------------------------

    def on_register(self, app: "Basis") -> None:
        """
        Called synchronously when the plugin is registered with a Basis app
        via ``include_plugin()``.  Use for validation or immediate setup.
        The ``app._plugins`` list will already contain previously registered
        plugins, so you can check for dependencies here.
        """
        pass

    async def on_startup(self, app: "Basis") -> None:
        """
        Called during the Basis app's lifespan startup phase.
        Use for async initialisation (database connections, background tasks, etc.).
        """
        pass

    async def on_shutdown(self, app: "Basis") -> None:
        """
        Called during the Basis app's lifespan shutdown phase.
        Use for cleanup (closing connections, flushing buffers, etc.).
        """
        pass

    def configure(self, **settings) -> "BasisPlugin":
        """
        Apply user configuration to this plugin.

        Returns ``self`` so it can be chained::

            app.include_plugin(
                auth_plugin.configure(secret_key="...", session_ttl=7200)
            )

        Plugin authors can read settings via ``self._settings``.
        """
        self._settings.update(settings)
        return self
