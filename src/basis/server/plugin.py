from pathlib import Path

from fastapi import APIRouter
from basis.server.db import ModelRegistryMixin


class BasisPlugin(ModelRegistryMixin):
    """
    A self-contained, route-aware bundle that can be registered into a Basis
    app via ``app.include_plugin(plugin)``.

    A plugin declares:
    - A URL prefix for its HTTP routes (``prefix``).
    - An optional directory of Python/HTML/CSS component files to serve as
      static assets so PyScript can import them (``static_dir`` / ``static_mount``).
    - Any number of REST endpoints via ``@plugin.get``, ``@plugin.post``, etc.
      (or directly via ``@plugin.router.get`` for full FastAPI expressiveness).
    - Server actions via the bare ``@server_action`` decorator (unchanged) —
      these self-register in the global ``_action_registry`` on import and are
      reached by clients through the global ``POST /basis/api/action`` endpoint.

    Example
    -------
    ::

        # my_chat/__init__.py
        from pathlib import Path
        from basis.server.plugin import BasisPlugin
        from basis.shared.actions import server_action

        plugin = BasisPlugin(
            prefix="/chat",
            static_dir=Path(__file__).parent,
            static_mount="/chat",
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

        # app.py
        from basis import Basis
        from my_chat import plugin as chat_plugin

        app = Basis()
        app.bootstrap()
        app.include_plugin(chat_plugin)
    """

    def __init__(
        self,
        *,
        prefix: str,
        static_dir: str | Path | None = None,
        static_mount: str | None = None,
        name: str | None = None,
        tags: list[str] | None = None,
    ):
        """
        Parameters
        ----------
        prefix:
            URL prefix applied to all routes declared on this plugin's router
            (e.g. ``"/chat"``).  Leading slash is required; trailing slash is
            stripped automatically.
        static_dir:
            Filesystem path to the directory containing the plugin's component
            files (.py, .html, .css).  When provided these files are served as
            static assets so PyScript can fetch and execute them.
        static_mount:
            URL path at which ``static_dir`` is mounted.  Defaults to
            ``prefix`` when not supplied.
        name:
            Optional human-readable identifier used when registering the static
            mount.  Defaults to a sanitised version of ``prefix``.
        tags:
            OpenAPI tags applied to all routes on this plugin's router.
        """
        self.prefix = prefix.rstrip("/")
        self.static_dir = Path(static_dir) if static_dir else None
        self.static_mount = static_mount or self.prefix
        self.name = name or self.prefix.strip("/").replace("/", "_") or "plugin"
        self.models = set()
        self.actions = {}
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
            return wrapper

        if callable(func_or_name):
            return decorator(func_or_name)
        return decorator

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
            f"static_mount={self.static_mount!r}, "
            f"name={self.name!r})"
        )
