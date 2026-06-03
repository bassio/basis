import json

try:
    from pyscript import WebSocket, document
except ImportError:
    # Handle the backend environment gracefully
    WebSocket = None
    document = None

from basis.shared.bindings import ComponentSubscription

class Store:
    _registry = {}
    _pending_subscriptions = {}

    @classmethod
    def from_dict(cls, name:str, init_dict:dict):
        new_store = cls(name)

        for k, v in init_dict.items():
            new_store.__dict__[k] = v

        return new_store

    def serialize(self) -> dict:
        """
        Extract serialisable state from this Store instance.
        Skips private/dunder attributes and non-serialisable callables.
        """
        state = {}
        for k, v in self.__dict__.items():
            if k.startswith('_'):
                continue
            if callable(v):
                continue
            try:
                json.dumps(v)     # quick serialisability check
                state[k] = v
            except (TypeError, ValueError):
                pass
        return state

    def __init__(self, name: str):
        self.__dict__['_subscriptions'] = []
        self.__dict__['_name'] = name

        # Register in the global registry
        Store._registry[name] = self

        # Fulfill pending subscriptions
        if name in Store._pending_subscriptions:
            for subscribing_component_instance, attr_name in Store._pending_subscriptions.pop(name):
                self.add_subscription(subscribing_component_instance, attr_name)
                subscribed_field = f"${name}.{attr_name}" if attr_name else f"${name}"
                with subscribing_component_instance.refrain() as refrained:
                    if attr_name:
                        setattr(refrained, subscribed_field, getattr(self, attr_name, None))
                    else:
                        setattr(refrained, subscribed_field, self)

        # SSR Hydration
        if document:
            initial_state_script = document.getElementById("basis-initial-state")
            if initial_state_script:
                try:
                    state_data = json.loads(initial_state_script.textContent)
                    if name in state_data:
                        print("HYDRATING FROM initial_state_script")
                        for k, v in state_data[name].items():
                            setattr(self, k, v)
                except Exception as e:
                    print(f"Failed to hydrate store '{name}': {e}")

    def get_store_name(self):
        return self.__dict__['_name']
    
    #def __getitem__(self, item):
    #    return Store._registry[item]

    def add_subscription(self, component_instance, attr_name:str):
        if (component_instance, attr_name) not in self._subscriptions:
            new_subscription = ComponentSubscription(component_instance=component_instance,
                                                     attr=attr_name)
            self.__dict__['_subscriptions'].append(new_subscription)

    def remove_subscription(self, component_instance, attr_name:str):
        self.__dict__['_subscriptions'] = [
            sub for sub in self._subscriptions if sub != (component_instance, attr_name)
        ]

    def update(self, new_state: dict):
        """
        Apply a dictionary of updates to the store.
        Each update triggers reactivity via __setattr__.
        """
        for k, v in new_state.items():
            setattr(self, k, v)

    def __setattr__(self, key, value):
        try:
            old_value = self.__dict__.get(key)
        except KeyError:
            old_value = None

        # On update, trigger react() on all subscribed components
        if value != old_value:

            super().__setattr__(key, value)
            
            store_name = self.get_store_name()

            for component, attr_name in self._subscriptions:
                # We tell the component to react to the store's "name"
                # so it re-evaluates bindings starting with `{$store_name.xxx}`
                if key == attr_name:
                    component.react([f"${store_name}.{attr_name}"])
                elif attr_name == "":
                    # Whole-store subscription
                    component.react([f"${store_name}"])

class WebSocketStore(Store):
    def __init__(self, name: str, ws_url: str):
        super().__init__(name)
        
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

class ReactiveCollection(list):
    """
    A reactive wrapper for lists that includes metadata like loading state and errors.
    """
    def __init__(self, items=None):
        if items is None:
            items = []
        super().__init__(items)
        self.is_loading = False
        self.error = None

    def set_items(self, items):
        self.clear()
        self.extend(items)
