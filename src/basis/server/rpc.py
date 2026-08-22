"""Server-side RPC layer for basis actions.

A single ``POST /basis/api/action`` endpoint dispatches every server action by
its canonical path (``module.qualname``) — the same identity for both
``@server_action`` and ``@plugin.action`` (plugin actions register in the same
``_action_registry`` under that path, so there is no separate plugin endpoint
or name-based resolution).

This module owns the shared pipeline — payload parsing, store binding /
reconstruction, sync/async dispatch, response shape and error handling — so the
endpoint registration in :mod:`basis.server.app` stays a thin glue.
"""

import asyncio
import importlib
import inspect
import logging
import traceback

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("uvicorn.error")


async def _read_rpc_payload(request: Request) -> dict:
    """Parse the JSON body, raising 400 on malformed input."""
    try:
        return await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")


def _vfs_to_server_path(path: str, vfs_map: dict) -> str:
    """Rewrite a client VFS module prefix to its server import name.

    This reconciles the client VFS namespace with the server import namespace
    (the isomorphism invariant). It is a no-op when the names already match,
    which is the normal case.
    """
    parts = path.split(".")
    for i in range(len(parts) - 1, 0, -1):
        prefix = ".".join(parts[:i])
        if prefix in vfs_map:
            return ".".join([vfs_map[prefix]] + parts[i:])
    return path


def _registry_action(path: str, vfs_map: dict):
    """Resolve a canonical ``module.qualname`` action path to its callable.

    Looks up the global ``_action_registry`` (populated by both ``@server_action``
    and ``@plugin.action``), lazily importing the owning module when the action
    isn't registered yet. Raises 404 when nothing resolves.
    """
    from basis.shared.actions import _action_registry

    server_path = _vfs_to_server_path(path, vfs_map)
    func = _action_registry.get(server_path)
    if func is None and "." in server_path:
        module_name = server_path.rsplit(".", 2)[0]
        try:
            importlib.import_module(module_name)
            func = _action_registry.get(server_path)
        except ImportError:
            pass
    if func is None:
        raise HTTPException(status_code=404, detail=f"Action '{path}' not found")
    return func


def _resolve_action_store(store_name):
    """Resolve a store instance for an RPC, rebuilding it from its blueprint if
    the per-request registry reset wiped the live instance. Returns ``None`` for
    no store; raises ``KeyError`` if a named store cannot be resolved."""
    from basis.shared.store import Store

    if not store_name:
        return None
    instance = Store._registry.get(store_name)
    if not instance:
        instance = Store.reinstantiate(store_name)
        if instance is not None:
            Store._registry[store_name] = instance
    if instance is None:
        raise KeyError(store_name)
    return instance


def _resolve_rpc_store(store_name):
    """Resolve the RPC store, mapping a missing store to a 404."""
    try:
        return _resolve_action_store(store_name)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Store '{store_name}' not found")


async def _run_action(func, instance, args, kwargs):
    """Run a sync/async server action against an optional store instance."""
    if instance is not None:
        if inspect.iscoroutinefunction(func):
            return await func(instance, *args, **kwargs)
        return func(instance, *args, **kwargs)
    if inspect.iscoroutinefunction(func):
        return await func(*args, **kwargs)
    return func(*args, **kwargs)


def _rpc_response(result, instance) -> JSONResponse:
    """Build the RPC response, attaching the store's new state when bound."""
    data = {"data": result}
    if instance is not None:
        data["new_state"] = instance.serialize()
    return JSONResponse(data)


def _log_rpc_error(path: str, exc: Exception):
    traceback.print_exc()
    logger.error(f"Error executing server action '{path}': {exc}")


def make_action_handler(app):
    """Build the async POST handler bound to *app*.

    *app* is captured (rather than reading ``request.app``) so app-bound stores
    (``_requires_app``) are always attached to the real Basis instance, even if
    the app is mounted under another ASGI application.
    """
    from basis.shared.store import attach_app_to_store

    async def action_handler(request: Request):
        payload = await _read_rpc_payload(request)
        path = payload.get("path")
        if not path:
            raise HTTPException(status_code=400, detail="'path' is required")
        vfs_map = getattr(app.state, "vfs_to_server_module", {})
        func = _registry_action(path, vfs_map)
        store = _resolve_rpc_store(payload.get("store_name"))
        attach_app_to_store(store, app)
        try:
            result = await _run_action(
                func, store, payload.get("args", []), payload.get("kwargs", {})
            )
            return _rpc_response(result, store)
        except Exception as e:
            _log_rpc_error(path, e)
            raise HTTPException(status_code=500, detail=str(e))

    return action_handler

