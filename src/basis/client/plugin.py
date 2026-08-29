import keyword
from functools import wraps
from typing import Any, cast, Callable, TypeVar

T = TypeVar("T", bound=Callable[..., Any])


def _is_valid_plugin_name(name: str) -> bool:
    return name.isidentifier() and not keyword.iskeyword(name)


def _sanitize_plugin_name(value: str) -> str:
    out = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in value)
    if not out:
        out = "plugin"
    if out[0].isdigit():
        out = "_" + out
    if keyword.iskeyword(out):
        out += "_"
    return out


def _resolve_plugin_name(name: str | None, prefix: str) -> str:
    if name is not None:
        if not _is_valid_plugin_name(name):
            raise ValueError(
                f"Plugin name {name!r} must be a valid Python identifier "
                f"(no spaces, hyphens, or leading digits, and not a Python "
                f"keyword) — it is used as $plugins.<name> and the client "
                f"proxy attribute."
            )
        return name
    return _sanitize_plugin_name(prefix.strip("/").replace("/", "_") or "plugin")


class APIRouter:
    def __init__(self, *args, **kwargs):
        pass
        self.routes = []
        self.on_startup = []
        self.on_shutdown = []
        self.lifespan = None
        self.deprecated = None
        from contextlib import asynccontextmanager
        @asynccontextmanager
        async def dummy_lifespan(app):
            yield
        self.lifespan_context = dummy_lifespan
    def get(self, *args, **kwargs):
        return lambda f: f
    def post(self, *args, **kwargs):
        return lambda f: f
    def put(self, *args, **kwargs):
        return lambda f: f
    def delete(self, *args, **kwargs):
        return lambda f: f
    def patch(self, *args, **kwargs):
        return lambda f: f
    def add_api_route(self, *args, **kwargs):
        pass

class ModelRegistryMixin:
    def model(self, modelcls=None):
        if modelcls is not None:
            return modelcls
        return lambda cls: cls
    def expose(self, url: str, method: str = "GET", one: bool = False, relations: list[str]|None = None):
        def decorator(cls):
            if not hasattr(cls, "__endpoints__"):
                cls.__endpoints__ = {}
            
            prefix = getattr(self, "prefix", "")
            full_url = url
            if prefix:
                full_url = f"{prefix.rstrip('/')}/{url.lstrip('/')}"
                
            cls.__endpoints__[(method.upper(), one)] = full_url
            return cls
        return decorator

class BasisPlugin(ModelRegistryMixin):
    #: Contribution classification (mirrors the server class): ``"plugin"``
    #: or ``"theme"`` — the partition key between the plugin and theme managers.
    kind: str = "plugin"

    def __init__(
        self,
        *,
        prefix: str,
        serving_dir: Any = None,
        serving_mount: str | None = None,
        name: str | None = None,
        tags: list[str] | None = None,
        requires: list[str] | None = None,
    ):
        self.prefix = prefix.rstrip("/")
        self.serving_dir = serving_dir
        self.serving_mount = serving_mount or self.prefix
        self.name = _resolve_plugin_name(name, self.prefix)
        self.requires = requires or []
        self.models = set()
        self._settings = {}
        self._region_items = []
        self._store_items = []
        self.router = APIRouter(prefix=self.prefix, tags=tags or [])

    def action(self, func_or_name: T | str | None = None, name: str | None = None) -> Any:
        def decorator(func: T) -> T:
            action_name = name
            if not action_name and isinstance(func_or_name, str):
                action_name = func_or_name
            if not action_name:
                action_name = func.__name__

            # Canonical RPC path — the same module.qualname rule as @server_action,
            # so client and server resolve the action identically.
            canonical_path = f"{func.__module__}.{func.__qualname__}"

            @wraps(func)
            async def wrapper(*args, **kwargs):
                from basis.client.actions import call_action

                store_name = None
                from basis.shared.store import Store
                if args and isinstance(args[0], Store):
                    store_name = args[0].get_store_name()
                    args = args[1:]

                return await call_action(
                    canonical_path, store_name, *args,
                    action_name=action_name, plugin_name=self.name, **kwargs,
                )

            # Expose the action as an attribute so `await plugin.<action>()` works
            # on the client (the plugin object mirrors the server shim).
            setattr(self, action_name, wrapper)
            return cast(T, wrapper)

        if callable(func_or_name):
            return decorator(func_or_name)
        return decorator

    def get(self, path: str, **kwargs):
        return lambda f: f

    def add_to_region(self, region, component_cls, *, props=None, order=None, position="end"):
        """Client-side mirror of :meth:`basis.server.plugin.BasisPlugin.add_to_region`.

        No app exists client-side: the contribution is mirrored into the
        ``$regions`` store if present (an ephemeral runtime add — the SSR/CSR
        initial state is authoritative on boot). Returns a ``RegionHandle``.
        """
        from basis.plugins.regions.registry import (
            MIN_ORDER,
            RegionContribution,
            RegionHandle,
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
        try:
            from basis.shared.store import Store
            store = Store._registry.get("regions")
            if store is not None:
                store.add_local(region, contrib.cls_path, props=props or {}, order=order)
        except Exception:
            pass
        return RegionHandle(contrib, app=None, owner=self)

    def region(self, name, **kwargs):
        def decorator(cls):
            self.add_to_region(name, cls, **kwargs)
            return cls
        return decorator

    def store(self, func_or_name=None, name=None):
        """Client-side mirror of :meth:`basis.server.plugin.BasisPlugin.store`.

        The declaration is recorded so a plugin module imports identically on
        both sides; the wiring happens server-side at include time.
        """
        if name is None and isinstance(func_or_name, str):
            name = func_or_name

        def decorator(cls):
            self._store_items.append((name, cls))
            return cls

        if callable(func_or_name):
            return decorator(func_or_name)
        return decorator

    def include_store(self, app=None, store_cls=None, name=None):
        """Client-side mirror of the server store-inclusion API.

        No app exists client-side: if the store isn't already registered (e.g.
        hydrated from ``#basis-initial-state``), ensure it in the local registry
        as a pure reactive view. Returns the store instance (or ``None``).
        """
        from basis.shared.store import Store

        if name is None and store_cls is not None:
            instance = store_cls()
            name = instance.get_store_name()
        if name is None:
            return None
        instance = Store._registry.get(name)
        if instance is None and store_cls is not None:
            instance = store_cls(name)
            Store._registry[name] = instance
        return instance

    def post(self, path: str, **kwargs):
        return lambda f: f

    def put(self, path: str, **kwargs):
        return lambda f: f

    def delete(self, path: str, **kwargs):
        return lambda f: f

    def patch(self, path: str, **kwargs):
        return lambda f: f

    # Lifecycle hooks (no-ops on client)
    def on_register(self, app=None): pass
    async def on_startup(self, app=None): pass
    async def on_shutdown(self, app=None): pass

    def configure(self, **settings):
        self._settings.update(settings)
        return self
