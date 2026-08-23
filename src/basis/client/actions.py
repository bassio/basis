import json
from typing import Any


async def _post_rpc(payload: dict) -> Any:
    """POST an RPC payload to ``/basis/api/action`` and apply any ``new_state``
    to the target store."""
    try:
        from pyodide.http import pyfetch
    except ImportError:
        # Fallback for non-PyScript environments (e.g. tests)
        print("Warning: pyfetch not available. Mocking RPC call to /basis/api/action")
        return None

    response = await pyfetch(
        "/basis/api/action",
        method="POST",
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload),
    )

    if not response.ok:
        error_text = await response.string()
        raise Exception(
            f"Server action failed with status {response.status}: {error_text}"
        )

    result = await response.json()

    # Handle state synchronization. Dependent app-bound stores re-sync through
    # their own cross-store DAG edges (e.g. $regions observes $plugins.items),
    # which fire on the setattr inside update() — no framework-level dependency
    # registry here.
    if "new_state" in result and payload.get("store_name"):
        from basis.shared.store import Store
        store = Store._registry.get(payload["store_name"])
        if store:
            store.update(result["new_state"])

    return result.get("data")


async def call_action(
    path,
    store_name: str | None = None,
    *args,
    action_name: str | None = None,
    plugin_name: str | None = None,
    **kwargs,
) -> Any:
    """Call a server action from the client by its canonical path.

    ``path`` is the canonical ``module.qualname`` identity for both
    ``@server_action`` and ``@plugin.action`` (the latter registers under the
    same rule). ``store_name`` is sent when the action is bound to a store so
    its ``new_state`` is applied back to that store on the client.
    ``action_name`` / ``plugin_name`` are optional self-describing metadata.
    """
    payload = {
        "path": path,
        "store_name": store_name,
        "args": list(args),
        "kwargs": kwargs,
    }
    if action_name:
        payload["action_name"] = action_name
    if plugin_name:
        payload["plugin_name"] = plugin_name
    return await _post_rpc(payload)
