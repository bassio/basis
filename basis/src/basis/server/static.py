import os
from pathlib import Path
from starlette.staticfiles import StaticFiles
from starlette.responses import Response, FileResponse
from starlette.types import Scope, Receive, Send

from basis.server.ast_utils import strip_server_actions

class BasisStaticFiles(StaticFiles):
    """
    A specialized StaticFiles handler that strips @server_action bodies 
    from .py files before serving them to the client.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache: dict[str, tuple[float, str]] = {} # path -> (mtime, content)

    async def get_response(self, path: str, scope: Scope) -> Response:
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
                        return Response(cached_content, media_type="text/x-python")
                
                # Read and transform
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        source = f.read()
                    
                    transformed = strip_server_actions(source)
                    
                    # Update cache
                    self._cache[full_path] = (mtime, transformed)
                    
                    return Response(transformed, media_type="text/x-python")
                except Exception:
                    # Fallback to original response if transformation fails
                    return response
                    
        return response
