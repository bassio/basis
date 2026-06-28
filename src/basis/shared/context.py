import asyncio
from contextvars import ContextVar
import sys

from typing import Optional, Any

IS_CLIENT = "pyscript" in sys.modules

# Platform-agnostic base URL context (isomorphic)
# On the server, this is set by the Basis app during SSR.
# On the client, this remains None (components use window.location or relative paths).
base_url_var: ContextVar[Optional[str]] = ContextVar("base_url", default=None)

# Platform-agnostic database session context (isomorphic)
# On the server, this is set by the Basis app during SSR to execute direct DB queries.
# On the client, this remains None (stores use REST/WebSocket endpoints).
db_session_var: ContextVar[Optional[Any]] = ContextVar("db_session", default=None)

def get_base_url() -> Optional[str]:
    """Return the current base URL if set in the context."""
    return base_url_var.get()


class ContextVarProxyDict(dict):
    def __init__(self, name):
        super().__init__()
        self._name = name
        self._var = ContextVar(name)
        self._clientside_fallback_dict = {}

    def _get_dict(self):
        if IS_CLIENT:
            return self._clientside_fallback_dict

        try:
            d = self._var.get()
            created = False
        except LookupError:
            d = {}
            self._var.set(d)
            created = True
        
        try:
            task = asyncio.current_task()
            task_name = task.get_name() if task else "NoTask"
        except Exception:
            task_name = "ErrorTask"
            
        # print(f"[REGISTRY-DEBUG] {self._name} - Task: {task_name}, DictID: {id(d)}, Created: {created}, Len: {len(d)}")
        
        return d


    def __getitem__(self, key):
        return self._get_dict()[key]

    def __setitem__(self, key, value):
        self._get_dict()[key] = value

    def __delitem__(self, key):
        del self._get_dict()[key]

    def __contains__(self, key):
        return key in self._get_dict()

    def __len__(self):
        return len(self._get_dict())

    def __iter__(self):
        return iter(self._get_dict())

    def keys(self):
        return self._get_dict().keys()

    def values(self):
        return self._get_dict().values()

    def items(self):
        return self._get_dict().items()

    def get(self, key, default=None):
        return self._get_dict().get(key, default)

    def clear(self):
        self._get_dict().clear()

    def pop(self, key, default=None):
        return self._get_dict().pop(key, default)

    def setdefault(self, key, default=None):
        return self._get_dict().setdefault(key, default)

    def update(self, *args, **kwargs):
        self._get_dict().update(*args, **kwargs)

    def __repr__(self):
        return repr(self._get_dict())

    def __str__(self):
        return str(self._get_dict())


