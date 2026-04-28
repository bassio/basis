import json

try:
    from js import WebSocket, document
except ImportError:
    # Handle the backend environment gracefully
    WebSocket = None
    document = None

class Store:
    _registry = {}

    @classmethod
    def from_dict(cls, name:str, init_dict:dict):
        new_store = cls(name)

        for k, v in init_dict.items():
            new_store.__dict__[k] = v

        return new_store

    def __init__(self, name: str):
        self.__dict__['_subscriptions'] = []
        self.__dict__['name'] = name

        # Register in the global registry
        Store._registry[name] = self

    def __getitem__(self, item):
        return Store._registry[item]

    def subscribe(self, component_instance, attr_name:str):
        if (component_instance, attr_name) not in self._subscriptions:
            self._subscriptions.append((component_instance, attr_name))

    def unsubscribe(self, component_instance, attr_name:str):
        self.__dict__['_subscriptions'] = [
            sub for sub in self._subscriptions if sub != (component_instance, attr_name)
        ]

    def __setattr__(self, key, value):
        try:
            old_value = self.__dict__.get(key)
        except KeyError:
            old_value = None

        super().__setattr__(key, value)

        # On update, trigger react() on all subscribed components
        if value != old_value:

            store_name = self.name

            for component, attr_name in self._subscriptions:
                # We tell the component to react to the store's "name"
                # so it re-evaluates bindings starting with `{store_name.xxx}`
                if key == attr_name:
                    component.react([f"${store_name}.{attr_name}"])

class WebSocketStore(Store):
    def __init__(self, name: str, ws_url: str):
        super().__init__(name)
        
        # SSR Hydration
        if document:
            initial_state_script = document.getElementById("basis-initial-state")
            if initial_state_script:
                try:
                    state_data = json.loads(initial_state_script.textContent)
                    if name in state_data:
                        for k, v in state_data[name].items():
                            setattr(self, k, v)
                except Exception as e:
                    print(f"Failed to hydrate store '{name}': {e}")

        # WebSocket connection
        if WebSocket:
            self.ws_url = ws_url
            self.ws = WebSocket.new(ws_url)
            self.ws.onmessage = self._on_message
    
    def _on_message(self, event):
        data = json.loads(event.data)
        # Update state directly; relying on base Store __setattr__ to notify subscribers
        for k, v in data.items():
            setattr(self, k, v)

    def dispatch(self, action: str, payload: dict):
        if self.ws and self.ws.readyState == 1: # OPEN
            self.ws.send(json.dumps({"action": action, "payload": payload}))
        else:
            print(f"WebSocket not open. Cannot dispatch action '{action}'.")
