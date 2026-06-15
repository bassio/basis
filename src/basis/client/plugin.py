from functools import wraps
from typing import Any, cast, Callable, TypeVar

T = TypeVar("T", bound=Callable[..., Any])

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
    def __init__(
        self,
        *,
        prefix: str,
        static_dir: Any = None,
        static_mount: str | None = None,
        name: str | None = None,
        tags: list[str] | None = None,
    ):
        self.prefix = prefix.rstrip("/")
        self.static_dir = static_dir
        self.static_mount = static_mount or self.prefix
        self.name = name or self.prefix.strip("/").replace("/", "_") or "plugin"
        self.models = set()
        self.router = APIRouter(prefix=self.prefix, tags=tags or [])

    def action(self, func_or_name: T | str | None = None, name: str | None = None) -> Any:
        def decorator(func: T) -> T:
            action_name = name
            if not action_name and isinstance(func_or_name, str):
                action_name = func_or_name
            if not action_name:
                action_name = func.__name__

            @wraps(func)
            async def wrapper(*args, **kwargs):
                from basis.client.actions import call_plugin_server_action

                store_name = None
                from basis.shared.store import Store
                if args and isinstance(args[0], Store):
                    store_name = args[0].get_store_name()
                    args = args[1:]

                return await call_plugin_server_action(self.name, action_name, store_name, *args, **kwargs)

            return cast(T, wrapper)

        if callable(func_or_name):
            return decorator(func_or_name)
        return decorator

    def get(self, path: str, **kwargs):
        return lambda f: f

    def post(self, path: str, **kwargs):
        return lambda f: f

    def put(self, path: str, **kwargs):
        return lambda f: f

    def delete(self, path: str, **kwargs):
        return lambda f: f

    def patch(self, path: str, **kwargs):
        return lambda f: f
