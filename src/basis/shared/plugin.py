import sys

IS_CLIENT = "pyscript" in sys.modules

if IS_CLIENT:
    from basis.client.plugin import BasisPlugin as ClientPlugin
    BasisPlugin = ClientPlugin
    # Client-safe placeholder for FastAPI's `Request`. Plugins declare HTTP
    # routes with `request: Request` annotations (importing `Request` from this
    # shim) — on the server it IS fastapi.Request, on the client it's an inert
    # placeholder because PyScript has no fastapi. The client `APIRouter`
    # shims are no-op decorators, so route handlers are never called
    # client-side — only their module-scope imports (annotations) must resolve.
    Request = object
else:
    from basis.server.plugin import BasisPlugin as ServerPlugin
    BasisPlugin = ServerPlugin
    from fastapi import Request

__all__ = ["BasisPlugin", "Request", "IS_CLIENT"]
