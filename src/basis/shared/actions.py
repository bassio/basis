import sys
from functools import wraps
from typing import Any, TypeVar, Callable, cast

# Framework check
IS_CLIENT = "pyscript" in sys.modules
IS_SERVER = not IS_CLIENT

# Global registry of actions for the server to resolve
# Maps "module.Class.method" -> func
_action_registry: dict[str, Callable] = {}

T = TypeVar("T", bound=Callable[..., Any])

def server_action(func: T) -> T:
    """
    Decorator to mark a method or function as a server action.
    - On the server: It registers the function for RPC calls.
    - On the client: It replaces the function with an async RPC proxy.
    """
    path = f"{func.__module__}.{func.__qualname__}"
    _action_registry[path] = func

    @wraps(func)
    async def wrapper(*args, **kwargs):
        if IS_CLIENT:
            from basis.client.actions import call_server_action
            
            # If it's a method on a Store, we need to pass the store name
            store_name = None
            from basis.shared.store import Store
            if args and isinstance(args[0], Store):
                store_name = args[0].get_store_name()
                # Remove 'self' from args for the network call
                args = args[1:]

            return await call_server_action(path, store_name, *args, **kwargs)
        else:
            # On the server, just execute normally
            # Note: This expects the function to be async or handles sync
            import asyncio
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)

    return cast(T, wrapper)

# Stubs for server-side dependencies to prevent import errors in PyScript
if IS_CLIENT:
    def Depends(dependency: Any = None) -> Any:
        return None
        
    class Session:
        pass
else:
    # On the server, we import the real things if available
    try:
        from fastapi import Depends
    except ImportError:
        def Depends(dependency: Any = None) -> Any: return None
        
    try:
        from sqlmodel import Session
    except ImportError:
        class Session: pass
