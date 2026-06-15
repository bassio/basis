from contextvars import ContextVar
from typing import Optional, Any

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

