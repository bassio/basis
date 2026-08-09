import asyncio
from string import Formatter
from basis.shared.bindings import safe_eval, safe_format_with_stores, ALLOWED_BUILTINS, extract_dependencies
from basis.shared.store import Store, ModelStore, ReactiveCollection
from basis.shared.component import Component, client, IS_CLIENT

try:
    from pyscript import fetch
except ImportError:
    pass


def resolve_value(val):
    if not isinstance(val, str) or "{" not in val:
        return val

    formatter = Formatter()

    try:
        parsed = list(formatter.parse(val))
    except ValueError:
        return val

    is_single_expr = len(parsed) == 1 and parsed[0][1] is not None and not parsed[0][0]

    deps, ast_trees = extract_dependencies(val, ALLOWED_BUILTINS)

    if is_single_expr:
        fname = parsed[0][1]
        ast_tree = ast_trees.get(fname)
        if ast_tree:
            res = safe_eval(fname, None, ALLOWED_BUILTINS, tree=ast_tree)
            if isinstance(res, str) and res.startswith("[Error: "):
                return None
            return res
        return None

    # Fallback to string formatting
    try:
        return safe_format_with_stores(
            val,
            None,
            ALLOWED_BUILTINS,
            Store._registry,
            {},
            ast_trees=ast_trees
        )
    except Exception:
        return val


class StoreProvider(Component):
    __tag__ = "store-provider"
    
    url = ""
    name = ""
    target = None
    _last_fetched_url = ""

    def __setattr__(self, key, value):
        old_value = getattr(self, key, None)

        # print(f"*****In __setattr__ for StoreProvider: {key}, {value}")
        
        super().__setattr__(key, value)
        
        # When 'url' changes dynamically via a binding, trigger a new fetch
        if key == "url" and value != old_value and value:
            if IS_CLIENT:
                asyncio.create_task(self.fetch_data())

    @classmethod
    def initialize(cls, container, **kwargs):
        name = kwargs.get("name", "")
        if name and name not in Store._registry:
            # Create store synchronously so children can bind to it
            Store(name)
            
        instance = super().initialize(container, **kwargs)
        
        # Schedule the fetch task if on client
        if IS_CLIENT:
            asyncio.create_task(instance.fetch_data())
        else:
            pass
            
        return instance

    async def server_load(self):
        if not self.url or not self.name or "{" in self.url:
            return
            
        url = self.url
        if url.startswith("/"):
            from basis.shared.context import get_base_url
            base_url = get_base_url()
            if base_url:
                url = base_url.rstrip("/") + url
            else:
                # Fallback for local development or if context is missing
                url = f"http://127.0.0.1:8000{url}"
            
        def _fetch():
            import urllib.request
            import json
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode())
                
        try:
            data = await asyncio.to_thread(_fetch)
            store = Store._registry.get(self.name)
            if store:
                store.__dict__["_ssr_url"] = self.url
                if self.target:
                    if isinstance(data, list):
                        setattr(store, self.target, ReactiveCollection(data))
                    else:
                        setattr(store, self.target, data)
                elif isinstance(data, list):
                    setattr(store, "items", ReactiveCollection(data))
                else:
                    for k, v in dict(data).items():
                        setattr(store, k, v)
        except Exception as e:
            print(f"Server load failed for {self.name}: {e}")

    @client
    async def fetch_data(self):

        # print(f"*****In fetch_data for url: {self.url}")
        
        if not self.url or not self.name:
            return
 
        if  "{" in self.url:
            return
            
        if getattr(self, "_last_fetched_url", None) == self.url:
            return
            
        store = Store._registry.get(self.name)
        if store:
            if getattr(store, "_hydrated_from_ssr", False) and getattr(store, "_ssr_url", None) == self.url:
                # print(f"[Basis] SSR Hydration Guard: skipping fetch for store {self.name}")
                store._hydrated_from_ssr = False
                self.__dict__["_last_fetched_url"] = self.url
                return

        try:

            response = await fetch(self.url)
            data = await response.json()
            
            if store:
                if self.target:
                    if isinstance(data, list):
                        # print("***Creating ReactiveCollection with target***")
                        setattr(store, self.target, ReactiveCollection(data))
                    else:
                        setattr(store, self.target, data)

                elif isinstance(data, list):
                    setattr(store, "items", ReactiveCollection(data))
                else:
                    for k, v in dict(data).items():
                        setattr(store, k, v)

                store.__dict__['_first_load_completed'] = True
                    
            self.__dict__["_last_fetched_url"] = self.url
            
        except Exception as e:
            print(f"Failed to fetch data for {self.name} from {self.url}: {e}")

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        # Override mount to avoid appending the dummy <slot></slot> template to the DOM.
        # This prevents orphan slot elements from polluting the SSR and client DOM.
        return cls.initialize(container, **attributes)

    def fill_slots(self, container):
        # Logical-only component; do not consume or distribute child nodes.
        pass

    def template(self):
        """
        <slot></slot>
        """


class ModelStoreProvider(Component):
    __tag__ = "model-store-provider"
    
    name = ""
    model = None
    one = False
    target = "items"
    
    def __init__(self):
        super().__init__()
        self.__dict__["_model_kwargs"] = {}
        self.__dict__["_last_kwargs_str"] = ""

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
            store.__dict__["_ssr_params"] = resolved_kwargs
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

        # Check SSR Hydration Guard
        if getattr(store, "_hydrated_from_ssr", False):
            ssr_params = getattr(store, "_ssr_params", None)
            if ssr_params is not None:
                # Compare current model kwargs with ssr_params
                match = True
                for k, v in self._model_kwargs.items():
                    if k not in ssr_params or str(ssr_params[k]) != str(v):
                        match = False
                        break
                if match:
                    print(f"[Basis] SSR Hydration Guard: skipping fetch for ModelStore {self.name}")
                    store._hydrated_from_ssr = False
                    self.__dict__["_last_kwargs_str"] = kwarg_str
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

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        # Override mount to avoid appending the dummy <slot></slot> template to the DOM.
        # This prevents orphan slot elements from polluting the SSR and client DOM.
        return cls.initialize(container, **attributes)

    def fill_slots(self, container):
        # Logical-only component; do not consume or distribute child nodes.
        pass

    def template(self):
        """
        <slot></slot>
        """
