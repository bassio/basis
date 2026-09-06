import hashlib
import importlib.util
import marshal
import os
from pathlib import Path
import time
from starlette.staticfiles import StaticFiles
from starlette.responses import Response, FileResponse
from starlette.types import Scope, Receive, Send

from basis.server.ast_utils import strip_server_actions


def _content_etag(data: bytes) -> str:
    """A strong validator over a response body: a quoted content hash."""
    return '"' + hashlib.sha256(data).hexdigest() + '"'


def _if_none_match(scope, if_none_match: str | None) -> str | None:
    """The client's ``If-None-Match`` value, if any (scope headers or explicit)."""
    if if_none_match is not None:
        return if_none_match
    headers = (scope or {}).get("headers") or ()
    for name, value in headers:
        if name.lower() == b"if-none-match":
            return value.decode("latin-1")
    return None


def conditional_response(body: bytes, media_type: str, *,
                         scope=None,
                         if_none_match: str | None = None,
                         headers: dict | None = None) -> Response:
    """Build a revalidate-able response: strong content-hash ``ETag`` +
    ``Cache-Control: no-cache`` so the browser revalidates (304) instead of
    re-downloading on every visit, while a content change still gets a fresh
    200 — correct under HMR / plugin toggles / per-page manifests (no
    time-based staleness).
    """
    etag = _content_etag(body)
    inm = _if_none_match(scope, if_none_match)
    if inm is not None and etag in [e.strip() for e in inm.split(",")]:
        response: Response = Response(status_code=304)
    else:
        response = Response(body, media_type=media_type)
    response.headers["etag"] = etag
    response.headers["cache-control"] = "no-cache"
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


def compile_to_pyc_bytes(source_code: str, filename: str = "<string>") -> bytes:
    """
    Compiles Python source code string into PEP 488 compliant .pyc bytecode bytes in-memory.
    """
    code_obj = compile(source_code, filename, 'exec')
    magic = importlib.util.MAGIC_NUMBER  # 4 bytes
    flags = (0).to_bytes(4, 'little')     # 4 bytes (0 = mtime-based)
    mtime = int(time.time()).to_bytes(4, 'little')  # 4 bytes
    size = len(source_code.encode('utf-8')).to_bytes(4, 'little')  # 4 bytes

    header = magic + flags + mtime + size
    payload = marshal.dumps(code_obj)
    return header + payload


class BasisStaticFiles(StaticFiles):
    """
    A specialized StaticFiles handler that strips @server_action bodies 
    from .py files before serving them to the client.
    """
    def __init__(self, *args, synthetic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache: dict[str, tuple[float, str]] = {} # path -> (mtime, content)
        #: mount-relative path -> in-memory generated source (headless components).
        #: Served only while no real file exists at that path — a real ``.py`` wins.
        self._synthetic = synthetic if synthetic is not None else {}

    def get_transformed_py_source(self, full_path: str) -> str:
        with open(full_path, "r", encoding="utf-8") as f:
            source = f.read()
            transformed = strip_server_actions(source)
            return transformed

    async def get_response(self, path: str, scope: Scope) -> Response:
        # Synthetic headless modules: serve the generated source only while no
        # real file exists at that path (a real ``.py`` always wins).
        if path in self._synthetic:
            full_path, _ = self.lookup_path(path)
            if not (full_path and os.path.isfile(full_path)):
                return conditional_response(
                    self._synthetic[path].encode("utf-8"),
                    "text/x-python",
                    scope=scope,
                )

        # Get the standard response first
        response = await super().get_response(path, scope)
        
        # Only transform .py files that were found (status 200)
        if path.endswith(".py") and response.status_code == 200:
            full_path, stat_result = self.lookup_path(path)
            
            if full_path and os.path.isfile(full_path):
                mtime = os.path.getmtime(full_path)
                
                # Check cache
                if full_path in self._cache:
                    cached_mtime, cached_content = self._cache[full_path]
                    if cached_mtime == mtime:
                        return conditional_response(
                            cached_content.encode("utf-8"),
                            "text/x-python",
                            scope=scope,
                        )
                
                # Read and transform
                try:
                    transformed = self.get_transformed_py_source(full_path)
                    
                    # Update cache
                    self._cache[full_path] = (mtime, transformed)

                    return conditional_response(
                        transformed.encode("utf-8"),
                        "text/x-python",
                        scope=scope,
                    )
                
                except Exception:
                    # Fallback to original response if transformation fails
                    return response
                    
        return response


class BasisStaticFilesPyc(BasisStaticFiles):
    """
    A specialized StaticFiles handler that compiles served Python files to .pyc bytecode
    in-memory after stripping @server_action bodies, caching bytecode in RAM.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache_pyc: dict[str, tuple[float, bytes]] = {}  # full_path -> (mtime, pyc_bytes)

    async def get_response(self, path: str, scope: Scope) -> Response:
        if path.endswith(".pyc"):
            py_path = path[:-1]  # strip trailing 'c' -> '.py'
            # Synthetic headless module in pyc mode: compile the generated source
            # in-memory (mirrors the real-file path below) while no real ``.py``
            # exists at that path.
            if py_path in self._synthetic:
                full_path, _ = self.lookup_path(py_path)
                if not (full_path and os.path.isfile(full_path)):
                    try:
                        pyc_bytes = compile_to_pyc_bytes(
                            self._synthetic[py_path], filename=py_path
                        )
                    except Exception:
                        pass
                    else:
                        return conditional_response(
                            pyc_bytes,
                            "application/x-bytecode.python",
                            scope=scope,
                        )
            full_path, _ = self.lookup_path(py_path)

            if full_path and os.path.isfile(full_path):
                mtime = os.path.getmtime(full_path)

                if full_path in self._cache_pyc:
                    cached_mtime, cached_bytes = self._cache_pyc[full_path]
                    if cached_mtime == mtime:
                        return conditional_response(
                            cached_bytes,
                            "application/x-bytecode.python",
                            scope=scope,
                        )

                try:
                    transformed = self.get_transformed_py_source(full_path)
                    pyc_bytes = compile_to_pyc_bytes(transformed, filename=full_path)
                    self._cache_pyc[full_path] = (mtime, pyc_bytes)
                    return conditional_response(
                        pyc_bytes,
                        "application/x-bytecode.python",
                        scope=scope,
                    )
                except Exception:
                    # If bytecode compilation fails, fallback to super class handling
                    pass

        return await super().get_response(path, scope)

