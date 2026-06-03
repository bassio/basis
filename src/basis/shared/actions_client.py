import json
from typing import Any

async def call_server_action(path: str, store_name: str | None, *args, **kwargs) -> Any:
    """
    Makes an HTTP POST request to the server to execute an action.
    """
    # Use pyfetch from pyodide.http (available in PyScript)
    try:
        from pyodide.http import pyfetch
    except ImportError:
        # Fallback for non-PyScript environments (e.g. tests)
        print(f"Warning: pyfetch not available. Mocking RPC call to {path}")
        return None

    payload = {
        "path": path,
        "store_name": store_name,
        "args": list(args),
        "kwargs": kwargs
    }
    
    response = await pyfetch(
        "/basis/api/action",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload)
    )
    
    if not response.ok:
        error_text = await response.string()
        raise Exception(f"Server action '{path}' failed with status {response.status}: {error_text}")
        
    result = await response.json()
    
    # Handle state synchronization
    if "new_state" in result and store_name:
        from basis.shared.store import Store
        store = Store._registry.get(store_name)
        if store:
            store.update(result["new_state"])
            
    return result.get("data")
