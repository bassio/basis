import asyncio
from string import Formatter
from basis.shared.bindings import safe_eval, safe_format, ALLOWED_BUILTINS, extract_dependencies
from basis.shared.errors import is_error_string
from basis.shared.store import Store, ModelStore, ReactiveCollection
from basis.shared.component import Component, client, IS_CLIENT

try:
    from pyscript import fetch
except ImportError:
    pass


def resolve_value(val):
    # A "[Error: ...]" sentinel means a previous evaluation failed —
    # treat it as "cannot resolve yet" rather than passing the raw string.
    if is_error_string(val):
        return None
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
            # record=False: this is a *probe* (can the kwarg be resolved yet?).
            # Failure is the normal "provider not ready" state and must be silent —
            # caller skips the fetch.  Eval helpers return "" on failure when a
            # sink is registered; treat both the "[Error: ...]" sentinel and ""
            # as "cannot resolve yet".
            res = safe_eval(fname, None, ALLOWED_BUILTINS, tree=ast_tree, record=False)
            if res is None or res == "" or is_error_string(res):
                return None
            return res
        return None

    # Fallback to string formatting
    try:
        res = safe_format(
            val,
            None,
            ALLOWED_BUILTINS,
            ast_trees=ast_trees,
            record=False,
        )
        if res == "" or is_error_string(res):
            return None
        return res
    except Exception:
        return val


def _apply_provider_data(store, data, target=None) -> None:
    if target:
        value = ReactiveCollection(data) if isinstance(data, list) else data
        store.apply_state({target: value})
    elif isinstance(data, list):
        store.apply_state({"items": ReactiveCollection(data)})
    else:
        store.apply_state(dict(data))


def _model_fields(item) -> dict:
    values = item.__dict__ if hasattr(item, "__dict__") else item
    return {key: value for key, value in values.items() if not key.startswith("_")}


class StoreProvider(Component):
    __tag__ = "store-provider"
    
    url = ""
    name = ""
    target = None
    _last_fetched_url = ""

    def __setattr__(self, key, value):
        old_value = getattr(self, key, None)

        super().__setattr__(key, value)
        
        # When 'url' changes dynamically via a binding, trigger a new fetch
        if key == "url" and value != old_value and value:
            if IS_CLIENT:
                asyncio.create_task(self.fetch_data())

    @classmethod
    def initialize(cls, container, _creation_inputs=None, **kwargs):
        name = kwargs.get("name", "")
        if name and name not in Store._registry:
            # Create the store synchronously so children can bind to it. Prefer
            # the canonical factory (proper subclass + constructor args); fall back
            # to a plain Store(name) for config-only names. Never a raw plain
            # Store(name) when a blueprint exists — that would trip the conflict
            # guard and lose subclass constructor state.
            Store.reinstantiate(name) or Store(name)
            
        instance = super().initialize(
            container,
            _creation_inputs=_creation_inputs,
            **kwargs,
        )
        
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
                _apply_provider_data(store, data, self.target)
        except Exception as e:
            print(f"Server load failed for {self.name}: {e}")

    @client
    async def fetch_data(self):

        if not self.url or not self.name:
            return
 
        if  "{" in self.url:
            return
            
        if getattr(self, "_last_fetched_url", None) == self.url:
            return
            
        store = Store._registry.get(self.name)
        if store and store._consume_initial_fetch(url=self.url):
            self.__dict__["_last_fetched_url"] = self.url
            return

        try:

            response = await fetch(self.url)
            data = await response.json()
            
            if store:
                _apply_provider_data(store, data, self.target)
                store.__dict__['_first_load_completed'] = True
                    
            self.__dict__["_last_fetched_url"] = self.url
            
        except Exception as e:
            print(f"Failed to fetch data for {self.name} from {self.url}: {e}")

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        # Override mount to avoid appending the dummy <slot></slot> template to the DOM.
        # This prevents orphan slot elements from polluting the SSR and client DOM.
        return cls.initialize(container, **attributes)

    def fill_slots(self, container=None):
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
    def initialize(cls, container, _creation_inputs=None, **kwargs):
        name = kwargs.get("name", "")
        model = kwargs.get("model", None)
        
        if name and model and name not in Store._registry:
            ModelStore(name, model)
            
        instance = super().initialize(
            container,
            _creation_inputs=_creation_inputs,
            **kwargs,
        )
        
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
                    store.apply_state(_model_fields(data))
            else:
                data = await store.fetch_all(**resolved_kwargs)
                _apply_provider_data(store, data, self.target or "items")
        except Exception as e:
            print(f"Server load failed for ModelStore {self.name}: {e}")

    @client
    async def fetch_data(self):
        if not self.name or not self.model:
            return
            
        for v in self._model_kwargs.values():
            if v is None or (isinstance(v, str) and "{" in v):
                return
                
        kwarg_str = str(self._model_kwargs)
        if getattr(self, "_last_kwargs_str", None) == kwarg_str:
            return
            
        store = Store._registry.get(self.name)
        if not isinstance(store, ModelStore):
            return

        if store._consume_initial_fetch(params=self._model_kwargs):
            self.__dict__["_last_kwargs_str"] = kwarg_str
            return

        try:
            if self.one:
                data = await store.fetch_one(**self._model_kwargs)
                if data:
                    store.apply_state(_model_fields(data))
            else:
                data = await store.fetch_all(**self._model_kwargs)
                _apply_provider_data(store, data, self.target or "items")
                    
            self.__dict__["_last_kwargs_str"] = kwarg_str
            
        except Exception as e:
            print(f"Failed to fetch data for ModelStore {self.name}: {e}")

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        # Override mount to avoid appending the dummy <slot></slot> template to the DOM.
        # This prevents orphan slot elements from polluting the SSR and client DOM.
        return cls.initialize(container, **attributes)

    def fill_slots(self, container=None):
        # Logical-only component; do not consume or distribute child nodes.
        pass

    def template(self):
        """
        <slot></slot>
        """
