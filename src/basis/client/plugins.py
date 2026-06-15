import json
import re
from basis.client.actions import call_plugin_server_action
from basis.shared.store import Store

class PluginProxy:
    def __init__(self, name: str, actions: list[str]):
        self._name = name
        for action_name in actions:
            setattr(self, action_name, self._make_action(action_name))
            
    def _make_action(self, action_name: str):
        async def action(*args, **kwargs):
            store_name = None
            if args and isinstance(args[0], Store):
                store_name = args[0].get_store_name()
                args = args[1:]
            return await call_plugin_server_action(self._name, action_name, store_name, *args, **kwargs)
        return action

class PluginsRegistry:
    pass

plugins = PluginsRegistry()

# Dynamically construct proxies by fetching the registry from the backend
try:
    from pyodide.http import open_url
    res = open_url("/basis/api/plugins-registry")
    registry = json.loads(res.read())
except Exception:
    # Fallback for non-browser/test environments
    registry = {}

for plugin_name, actions in registry.items():
    safe_name = re.sub(r'\W+', '_', plugin_name.lower().replace("plugin", "")).strip("_")
    setattr(plugins, safe_name, PluginProxy(plugin_name, actions))
