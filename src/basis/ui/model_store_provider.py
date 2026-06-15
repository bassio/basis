import asyncio
from basis.shared.store import Store, ModelStore, ReactiveCollection
from basis.shared.component import Component, client, IS_CLIENT

def resolve_value(val):
    if not isinstance(val, str) or "{" not in val:
        return val
        
    if val.startswith("{") and val.endswith("}") and val.count("{") == 1:
        expr = val[1:-1]
        if expr.startswith("$"):
            parts = expr.strip("$").split(".")
            store_name = parts[0]
            if store_name in Store._registry:
                curr = Store._registry[store_name]
                for attr in parts[1:]:
                    if hasattr(curr, attr):
                        curr = getattr(curr, attr)
                    elif isinstance(curr, dict) and attr in curr:
                        curr = curr[attr]
                    else:
                        return None
                return curr
                
    # Fallback to string formatting
    try:
        from basis.shared.bindings import safe_format_with_stores, ALLOWED_BUILTINS
        return safe_format_with_stores(
            val,
            None,
            ALLOWED_BUILTINS,
            Store._registry,
            {}
        )
    except:
        return val

class ModelStoreProvider(Component):
    __tag__ = "model-store-provider"
    
    name = ""
    model = None
    one = False
    target = "items"
    
    def __init__(self):
        super().__init__()
        self._model_kwargs = {}
        self._last_kwargs_str = ""

    def __setattr__(self, key, value):
        old_value = getattr(self, key, None)
        
        super().__setattr__(key, value)
        
        # If it's a dynamic kwarg, update _model_kwargs and fetch
        if hasattr(self, "_model_kwargs") and key in self._model_kwargs:
            self._model_kwargs[key] = value
            # fetch only if changed
            if value != old_value:
                if IS_CLIENT:
                    asyncio.create_task(self.fetch_data())

    @classmethod
    def initialize(cls, container, **kwargs):
        name = kwargs.get("name", "")
        model = kwargs.get("model", None)
        
        if name and model and name not in Store._registry:
            # Create ModelStore synchronously
            ModelStore(name, model)
            
        instance = super().initialize(container, **kwargs)
        
        # Capture the custom kwargs for fetching
        for k, v in kwargs.items():
            if k not in ["name", "model", "one", "target"]:
                instance._model_kwargs[k] = getattr(instance, k, v)
        
        if IS_CLIENT:
            asyncio.create_task(instance.fetch_data())
            
        return instance

    async def server_load(self):
        if not self.name or not self.model:
            return
            
        store = Store._registry.get(self.name)
        if not isinstance(store, ModelStore):
            return

        resolved_kwargs = {}
        for k, v in self._model_kwargs.items():
            val = resolve_value(v)
            if val is None or (isinstance(val, str) and "{" in val):
                return
            resolved_kwargs[k] = val

        try:
            if self.one:
                data = await store.fetch_one(**resolved_kwargs)
                if data:
                    # Spread flat
                    for k, v in data.__dict__.items():
                        if not k.startswith("_"):
                            setattr(store, k, v)
            else:
                data = await store.fetch_all(**resolved_kwargs)
                if self.target:
                    setattr(store, self.target, ReactiveCollection(data))
                else:
                    setattr(store, "items", ReactiveCollection(data))
        except Exception as e:
            print(f"Server load failed for ModelStore {self.name}: {e}")

    @client
    async def fetch_data(self):
        if not self.name or not self.model:
            return
            
        # Check if any kwarg is None or still unresolved template syntax "{"
        for v in self._model_kwargs.values():
            if v is None or (isinstance(v, str) and "{" in v):
                return
                
        kwarg_str = str(self._model_kwargs)
        if getattr(self, "_last_kwargs_str", None) == kwarg_str:
            return
            
        store = Store._registry.get(self.name)
        if not isinstance(store, ModelStore):
            return

        try:
            if self.one:
                data = await store.fetch_one(**self._model_kwargs)
                if data:
                    for k, v in data.__dict__.items():
                        if not k.startswith("_"):
                            setattr(store, k, v)
            else:
                data = await store.fetch_all(**self._model_kwargs)
                if self.target:
                    setattr(store, self.target, ReactiveCollection(data))
                else:
                    setattr(store, "items", ReactiveCollection(data))
                    
            self.__dict__["_last_kwargs_str"] = kwarg_str
            
        except Exception as e:
            print(f"Failed to fetch data for ModelStore {self.name}: {e}")

    def style(self):
        """
        model-store-provider {
            display: contents;
        }
        """

    def template(self):
        """
        <slot></slot>
        """
