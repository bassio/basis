import dataclasses
import json
import sys
from typing import Any

IS_CLIENT = "pyscript" in sys.modules or "pyodide" in sys.modules
IS_SERVER = not IS_CLIENT

def _is_server():
    return not ("pyscript" in sys.modules or "pyodide" in sys.modules)

def _get_pyfetch():
    if "pyodide.http" in sys.modules:
        return getattr(sys.modules["pyodide.http"], "pyfetch", None)
    return pyfetch

if IS_CLIENT:
    try:
        from pyscript import WebSocket, document
        from pyodide.http import pyfetch
    except ImportError:
        WebSocket = None
        document = None
        pyfetch = None
else:
    WebSocket = None
    document = None
    pyfetch = None

from basis.shared.bindings import ComponentSubscription
from basis.shared.context import ContextVarProxyDict
from basis.shared.db import _make_serializable
from basis.shared.reactive import ReactiveObject


def _format_config(config: dict) -> str:
    """Render a store config snapshot for error messages, e.g. (model, url='/api')."""
    if "args" in config or "kwargs" in config:
        # Generic constructor-config capture: (args, kwargs).
        args = config.get("args", ())
        kwargs = config.get("kwargs", {})
    else:
        # Explicit flat config capture (e.g. ModelStore: {"model": ..., "url": ...}).
        args, kwargs = (), config
    parts = [repr(a) for a in args]
    parts += [f"{k}={v!r}" for k, v in kwargs.items()]
    return f"({', '.join(parts)})"


class Store(ReactiveObject):
    _registry = ContextVarProxyDict("store_registry")
    _pending_subscriptions = ContextVarProxyDict("store_pending_subscriptions")

    # Persistent config registry: name -> (cls, config_snapshot).
    # Unlike `_registry` (which is cleared per-request for SSR isolation), this is a plain
    # class-level dict that survives request boundaries, so server actions can re-instantiate
    # a store even after the per-request registry reset wiped the live instance.
    _store_blueprints: dict[str, tuple[type, dict]] = {}

    @classmethod
    def _capture_config(cls, *args, **kwargs) -> dict:
        """
        Snapshot the non-reactive constructor config (excluding the store name).
        Subclasses with explicit config (ModelStore, WebSocketStore, ...) override
        this to record a flat, explicit config dict instead of raw constructor
        plumbing.
        """
        return {
            "args": args,
            "kwargs": {k: v for k, v in kwargs.items() if k != "name"},
        }

    @classmethod
    def _restore(cls, name: str, config: dict) -> "Store":
        """Rebuild a store instance from a captured config snapshot."""
        return cls(name, *config["args"], **config["kwargs"])

    def __new__(cls, name: str | None = None, *args, **kwargs):
        instance = super().__new__(cls)
        if name is None:
            name = kwargs.get("name")
        if name is None:
            return instance

        # The store NAME is the registry key (the $<name> DSL identity), not part
        # of the config. Capture the non-reactive constructor config so SSR/RPC
        # can rebuild this store later (see `reinstantiate`).
        config = cls._capture_config(*args, **kwargs)

        existing = cls._store_blueprints.get(name)
        if existing is None:
            # First declaration wins — the canonical config used by RPC/SSR.
            cls._store_blueprints[name] = (cls, config)
        else:
            # Same name, same class + config → benign (this is exactly what
            # `reinstantiate`/SSR reconstruction does). Same name, DIFFERENT
            # config → genuine $name ambiguity → fail loudly.
            store_cls, store_config = existing
            try:
                same_config = store_cls is cls and store_config == config
            except Exception:
                # Exotic config whose __eq__ cannot be compared — treat as benign
                # rather than blocking reconstruction.
                same_config = True
            if not same_config:
                raise ValueError(
                    f"Cannot redeclare store '{name}': already registered as "
                    f"{store_cls.__name__}{_format_config(store_config)}, "
                    f"attempting to register as "
                    f"{cls.__name__}{_format_config(config)}. "
                    f"Store names are unique (they are the $<name> DSL identity); "
                    f"fix the duplicate declaration rather than re-declaring with "
                    f"new arguments."
                )
        return instance

    @classmethod
    def reinstantiate(cls, name: str) -> "Store | None":
        """
        Create a fresh instance of the store registered under *name* from its
        persistent config snapshot (class + config).  Returns ``None`` if no
        blueprint was ever recorded.

        This powers store-bound server actions: after the per-request registry
        reset wiped the live instance, the action handler can rebuild one with the
        same class and config.  Server actions are expected to read authoritative
        state from the DB (fresh sessions), so a fresh instance is safe.
        """
        blueprint = cls._store_blueprints.get(name)
        if not blueprint:
            return None
        store_cls, config = blueprint
        return store_cls._restore(name, config)

    @classmethod
    def all_names(cls) -> list[str]:
        """
        Names of every store ever declared (the persistent blueprint registry).

        Used by the auto-discovery convention: a Page whose ``stores`` is empty
        (or unset) defaults to hydrating *all* auto-discovered stores.
        """
        return list(cls._store_blueprints.keys())

    @classmethod
    def resolve(cls, name: str) -> "Store":
        """
        Create a store by name, preferring the canonical blueprint (proper
        subclass + constructor args); falls back to a plain ``Store(name)``
        for config-only names.
        """
        return cls.reinstantiate(name) or cls(name)

    @classmethod
    def from_dict(cls, name:str, init_dict:dict):
        new_store = cls(name)

        for k, v in init_dict.items():
            new_store.__dict__[k] = v

        return new_store

    def __init__(self, name: str):
        super().__init__()
        self.__dict__['_subscriptions'] = []
        self.__dict__['_name'] = name
        self.__dict__['_hydrated_from_ssr'] = False
        self.__dict__['_first_load_completed'] = False
        self.__dict__['loading'] = False
        self.__dict__['error'] = None

        # Register default public attributes as state nodes
        self._dag.get_or_create_state('loading')
        self._dag.get_or_create_state('error')

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
                        # print(f"HYDRATING store {name} FROM basis-initial-state")
                        for k, v in state_data[name].items():
                            setattr(self, k, v)
                        
                        self.__dict__['_hydrated_from_ssr'] = True
                        self.__dict__['_first_load_completed'] = True
                        
                        # Populate metadata if present under __basis_meta__
                        basis_meta = state_data.get("__basis_meta__", {})
                        if basis_meta:
                            ssr_params = basis_meta.get("ssr_params", {})
                            if name in ssr_params:
                                self.__dict__["_ssr_params"] = ssr_params[name]
                                
                            ssr_url = basis_meta.get("ssr_url", {})
                            if name in ssr_url:
                                self.__dict__["_ssr_url"] = ssr_url[name]

                except Exception as e:
                    print(f"Error: Failed to hydrate store '{name}': {e}")

        # Register @computed properties from the class
        self._init_computed()

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
                serializable_v = _make_serializable(v)
                json.dumps(serializable_v)     # quick serialisability check
                state[k] = serializable_v
            except (TypeError, ValueError):
                pass
        return state

    def __getattr__(self, name: str) -> Any:
        if name.startswith('_'):
            raise AttributeError(name)

        _first_load_completed = self.__dict__.get('_first_load_completed', False)
        if not _first_load_completed:
            return None
            
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def get_store_name(self):
        return self.__dict__['_name']

    def add_subscription(self, component_instance, attr_name:str):
        if (component_instance, attr_name) not in self._subscriptions:
            new_subscription = ComponentSubscription(component_instance=component_instance,
                                                     attr=attr_name)
            self.__dict__['_subscriptions'].append(new_subscription)

            # Register as EffectNode in the DAG
            store_name = self.get_store_name()
            effect_name = f"sub_{id(component_instance)}_{attr_name}"

            if attr_name:
                # Attribute-specific subscription
                def make_effect_callback(comp, sname, aname):
                    def callback():
                        comp.react([f"${sname}.{aname}"])
                    return callback

                self._dag.add_effect(
                    effect_name,
                    make_effect_callback(component_instance, store_name, attr_name),
                    [attr_name]
                )
            else:
                # Whole-store subscription (wildcard)
                def make_wildcard_callback(comp, sname):
                    def callback():
                        comp.react([f"${sname}"])
                    return callback

                self._dag.add_wildcard_effect(
                    effect_name,
                    make_wildcard_callback(component_instance, store_name)
                )

    def remove_subscription(self, component_instance, attr_name:str):
        self.__dict__['_subscriptions'] = [
            sub for sub in self._subscriptions if sub != (component_instance, attr_name)
        ]
        # Remove from DAG
        effect_name = f"sub_{id(component_instance)}_{attr_name}"
        self._dag.remove_effect(effect_name)

    def update(self, new_state: dict):
        """
        Apply a dictionary of updates to the store.
        Each update triggers reactivity via __setattr__.
        """
        for k, v in new_state.items():
            setattr(self, k, v)

    def __setattr__(self, key, value):
        # Delegate to ReactiveObject for DAG-based change detection and triggering.
        # ReactiveObject.__setattr__ handles private attrs, identity-first checks,
        # auto-creates StateNodes, and triggers DAG propagation to subscription EffectNodes.
        super().__setattr__(key, value)

class WebSocketStore(Store):
    @classmethod
    def _capture_config(cls, ws_url: str) -> dict:
        """Explicit non-reactive config snapshot (websocket url)."""
        return {"ws_url": ws_url}

    @classmethod
    def _restore(cls, name: str, config: dict) -> "WebSocketStore":
        return cls(name, **config)

    def __init__(self, name: str, ws_url: str):
        super().__init__(name)

        # WebSocket url + handle are non-reactive wiring, not state nodes.
        self.__dict__['_config'] = {"ws_url": ws_url}
        self.__dict__['_ws'] = None
        if WebSocket:
            self.__dict__['_ws'] = WebSocket.new(ws_url)
            self.__dict__['_ws'].onmessage = self._on_message

    @property
    def ws_url(self) -> str:
        return self.__dict__['_config']['ws_url']

    @property
    def ws(self):
        return self.__dict__.get('_ws')
    
    def _on_message(self, event):
        data = json.loads(event.data)
        # Update state directly; relying on base Store __setattr__ to notify subscribers
        for k, v in data.items():
            setattr(self, k, v)

    def dispatch(self, action: str, payload: dict):
        ws = self.__dict__.get('_ws')
        if ws and ws.readyState == 1: # OPEN
            ws.send(json.dumps({"action": action, "payload": payload}))
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


import re

def _get_item_id(x: Any) -> Any:
    if isinstance(x, dict):
        return x.get("id")
    return getattr(x, "id", None)


def _resolve_url_and_params(url_pattern: str, kwargs: dict) -> tuple[str, dict]:
    placeholders = re.findall(r"\{([^}]+)\}", url_pattern)
    params = {}
    for p in placeholders:
        if p not in kwargs:
            raise ValueError(f"Missing required path parameter '{p}' for URL pattern '{url_pattern}'")
        val = kwargs[p]
        if val is None or val == "" or val == "None":
            return "", {}
        params[p] = val
            
    resolved_url = url_pattern
    for p, val in params.items():
        resolved_url = resolved_url.replace(f"{{{p}}}", str(val))
            
    return resolved_url, params


def _matches_params(x: Any, params: dict) -> bool:
    if not params:
        return False
    for k, v in params.items():
        if isinstance(x, dict):
            val = x.get(k)
        else:
            val = getattr(x, k, None)
        if str(val) != str(v):
            return False
    return True


class ModelStore(Store):
    # Config attribute names are immutable metadata — never reactive state.
    _CONFIG_ATTRS = frozenset({"model", "model_name", "custom_url"})

    @classmethod
    def _capture_config(cls, model: Any, url: str | None = None) -> dict:
        """Explicit non-reactive config snapshot (model + endpoint url)."""
        return {"model": model, "url": url}

    @classmethod
    def _restore(cls, name: str, config: dict) -> "ModelStore":
        return cls(name, **config)

    def __init__(self, name: str, model: Any, url: str | None = None):
        super().__init__(name)
        # Non-reactive config: private dict, bypasses the DAG and serialize().
        self.__dict__['_config'] = {
            "model": model,
            "model_name": getattr(model, "__name__", str(model)),
            "url": url,
        }
        if 'items' not in self.__dict__:
            self.__dict__['items'] = []

        # SSR parity: when hydrated from #basis-initial-state the collection was
        # serialized as plain dicts.  Re-validate them into typed model
        # instances so a ModelStore's payload has the same shape as the CSR
        # fetch path (fetch_all -> model_validate), whichever route produced
        # the page.
        self._revalidate_hydrated_payloads()

    def _revalidate_hydrated_payloads(self) -> None:
        """Re-validate SSR-hydrated model payloads into typed instances.

        The SSR serializer emits ``items`` as plain dicts (``model_dump`` into
        ``#basis-initial-state``), while the CSR fetch path runs
        ``model_validate``.  This restores the invariant that ``items`` holds
        model instances on the client regardless of route.

        Only the collection attribute is touched: flat ``one=True`` fields,
        ``loading``/``error``, and non-ModelStore state are left as-is.
        Validation is best-effort — a payload that does not fit the schema
        keeps its plain-dict shape rather than breaking hydration.
        """
        if not self.__dict__.get('_hydrated_from_ssr'):
            return

        items = self.__dict__.get('items')
        if not isinstance(items, list) or not items:
            return
        # Already typed (instances), or a non-model payload — nothing to do.
        if not isinstance(items[0], dict):
            return

        validate = getattr(self.model, "model_validate", None)
        if validate is None:
            return

        try:
            revalidated = [
                validate(item) if isinstance(item, dict) else item
                for item in items
            ]
            # Parity with the CSR shape (the provider wraps in ReactiveCollection).
            setattr(self, "items", ReactiveCollection(revalidated))
        except Exception:
            pass

    def __setattr__(self, name, value):
        if name in self._CONFIG_ATTRS:
            raise AttributeError(
                f"{self.__class__.__name__} config '{name}' is read-only"
            )
        super().__setattr__(name, value)

    @property
    def model(self) -> Any:
        return self.__dict__['_config']['model']

    @property
    def model_name(self) -> str:
        return self.__dict__['_config']['model_name']

    @property
    def custom_url(self) -> str | None:
        return self.__dict__['_config']['url']

    def __getattr__(self, name: str) -> Any:
        if name.startswith('_'):
            raise AttributeError(name)
        
        # Check fields
        model = self.__dict__['_config'].get("model")
        if model is None:
            raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")
            
        if IS_SERVER:
            if name in model.model_fields:
                return None
        else:
            if name in [f.name for f in dataclasses.fields(model)]:
                return None
        
        # If not a valid field, it's a typo
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def _find_endpoint(self, method: str, one: bool) -> str | None:
        if self.custom_url:
            if one:
                return f"{self.custom_url.rstrip('/')}/{{id}}"
            return self.custom_url
        
        urls = getattr(self.model, "__endpoints__", {})
        return urls.get((method.upper(), one))

    async def fetch_all(self, **kwargs) -> list:
        
        if _is_server():
            from basis.shared.context import db_session_var
            session = db_session_var.get()
            if session:
                from sqlmodel import select
                statement = select(self.model)
                for k, v in kwargs.items():
                    if hasattr(self.model, k) and v is not None:
                        statement = statement.where(getattr(self.model, k) == v)
                self.items = list(session.exec(statement).all())
            return self.items

        url = self._find_endpoint("GET", one=False)
        if not url:
            print(f"Error: No GET endpoint found for {self.model_name}")
            return self.items

        resolved_url, params = _resolve_url_and_params(url, kwargs)
        if not resolved_url:
            return self.items

        query_params = {k: v for k, v in kwargs.items() if k not in params and v is not None}
        if query_params:
            from urllib.parse import urlencode
            resolved_url = f"{resolved_url}?{urlencode(query_params)}"

        self.loading = True

        try:
            pf = _get_pyfetch()
            response = await pf(resolved_url)
            if response.ok:
                data = await response.json()
                hydrated = [self.model.model_validate(item) if hasattr(self.model, "model_validate") else item for item in data]
                self.items = hydrated
                self.error = None
                self.__dict__['_first_load_completed'] = True
                self.loading = False
                return self.items
            else:
                self.error = f"Fetch failed: {response.status}"
        except Exception as e:
            self.error = str(e)
        finally:
            self.loading = False
        return self.items

    async def fetch_one(self, **kwargs) -> Any:
        url = self._find_endpoint("GET", one=True)
        if not url:
            print(f"Error: No GET (single) endpoint found for {self.model_name}")
            return None
        
        resolved_url, params = _resolve_url_and_params(url, kwargs)
        if not resolved_url:
            return None

        if IS_SERVER:
            # Server: use db_session_var if available
            from basis.shared.context import db_session_var
            session = db_session_var.get()
            item = None
            if session:
                from sqlmodel import select
                statement = select(self.model)
                for k, v in params.items():
                    if hasattr(self.model, k):
                        statement = statement.where(getattr(self.model, k) == v)
                for k, v in kwargs.items():
                    if hasattr(self.model, k) and k not in params:
                        statement = statement.where(getattr(self.model, k) == v)
                item = session.exec(statement).first()
            else:
                for x in self.items:
                    if _matches_params(x, params):
                        item = x
                        break
            if item:
                # Spread fields flat
                for k, v in item.__dict__.items():
                    if not k.startswith("_"):
                        setattr(self, k, v)
            return item


        self.loading = True

        try:
            response = await pyfetch(resolved_url)
            if response.ok:
                data = await response.json()
                item = self.model.model_validate(data) if hasattr(self.model, "model_validate") else data
                idx = -1
                for i, existing in enumerate(self.items):
                    if _matches_params(existing, params):
                        idx = i
                        break
                if idx != -1:
                    new_items = list(self.items)
                    new_items[idx] = item
                    self.items = new_items
                else:
                    self.items = self.items + [item]
                
                # Spread fields flat onto store
                for k, v in (item.__dict__ if hasattr(item, "__dict__") else item).items():
                    if not k.startswith("_"):
                        setattr(self, k, v)
                
                self.error = None
                self.__dict__['_first_load_completed'] = True
                self.loading = False
                return item

            else:
                self.error = f"Fetch failed: {response.status}"
        except Exception as e:
            self.error = str(e)
        finally:
            self.loading = False
        return None

    async def create(self, data: Any) -> Any:
        url = self._find_endpoint("POST", one=False)
        if not url:
            print(f"Error: No POST endpoint found for {self.model_name}")
            return None

        payload = data
        if hasattr(data, "model_dump"):
            payload = data.model_dump()
        elif hasattr(data, "__dict__"):
            payload = {k: v for k, v in data.__dict__.items() if not k.startswith("_")}

        old_items = list(self.items)

        temp_item = self.model.model_validate(payload) if hasattr(self.model, "model_validate") else payload
        if hasattr(temp_item, "id") and getattr(temp_item, "id") is None:
            setattr(temp_item, "id", "temp-" + str(len(self.items)))
        elif isinstance(temp_item, dict) and "id" not in temp_item:
            temp_item["id"] = "temp-" + str(len(self.items))
        
        self.items = self.items + [temp_item]

        if IS_SERVER:
            return temp_item

        self.__dict__["loading"] = True

        try:
            response = await pyfetch(
                url,
                method="POST",
                headers={"Content-Type": "application/json"},
                body=json.dumps(payload)
            )
            if response.ok:
                res_data = await response.json()
                saved_item = self.model.model_validate(res_data) if hasattr(self.model, "model_validate") else res_data
                new_items = [saved_item if (str(_get_item_id(x)) == str(_get_item_id(temp_item))) else x for x in old_items]
                self.items = new_items + [saved_item]
                self.error = None
                return saved_item
            else:
                self.error = f"Create failed: {response.status}"
                self.items = old_items
        except Exception as e:
            self.error = str(e)
            self.items = old_items
        return None

    async def update(self, *, data: Any = None, **kwargs) -> Any:
        url = self._find_endpoint("PATCH", one=True) or self._find_endpoint("PUT", one=True)
        if not url:
            print(f"Error: No PATCH/PUT endpoint found for {self.model_name}")
            return None

        resolved_url, params = _resolve_url_and_params(url, kwargs)

        payload = data
        if hasattr(data, "model_dump"):
            payload = data.model_dump()
        elif hasattr(data, "__dict__"):
            payload = {k: v for k, v in data.__dict__.items() if not k.startswith("_")}

        old_items = list(self.items)

        new_items = []
        for x in self.items:
            if _matches_params(x, params):
                if hasattr(x, "model_dump"):
                    dumped = x.model_dump()
                    dumped.update(payload)
                    new_items.append(self.model.model_validate(dumped))
                elif isinstance(x, dict):
                    updated_dict = dict(x)
                    updated_dict.update(payload)
                    new_items.append(updated_dict)
                else:
                    new_items.append(x)
            else:
                new_items.append(x)
        self.items = new_items

        try:
            from pyodide.http import pyfetch
        except ImportError:
            # Server: return updated item locally
            match = None
            for x in self.items:
                if _matches_params(x, params):
                    match = x
                    break
            return match

        try:
            method = "PATCH" if self._find_endpoint("PATCH", one=True) else "PUT"
            response = await pyfetch(
                resolved_url,
                method=method,
                headers={"Content-Type": "application/json"},
                body=json.dumps(payload)
            )
            if response.ok:
                res_data = await response.json()
                updated_item = self.model.model_validate(res_data) if hasattr(self.model, "model_validate") else res_data
                
                final_items = []
                for x in old_items:
                    if _matches_params(x, params):
                        final_items.append(updated_item)
                    else:
                        final_items.append(x)
                self.items = final_items
                self.error = None
                return updated_item
            else:
                self.error = f"Update failed: {response.status}"
                self.items = old_items
        except Exception as e:
            self.error = str(e)
            self.items = old_items
        return None

    async def delete(self, **kwargs) -> bool:
        url = self._find_endpoint("DELETE", one=True)
        if not url:
            print(f"Error: No DELETE endpoint found for {self.model_name}")
            return False

        resolved_url, params = _resolve_url_and_params(url, kwargs)
        old_items = list(self.items)

        new_items = []
        for x in self.items:
            if not _matches_params(x, params):
                new_items.append(x)
        self.items = new_items

        try:
            from pyodide.http import pyfetch
        except ImportError:
            # Server: success locally
            return True

        try:
            response = await pyfetch(resolved_url, method="DELETE")
            if response.ok:
                self.error = None
                return True
            else:
                self.error = f"Delete failed: {response.status}"
                self.items = old_items
                return False
        except Exception as e:
            self.error = str(e)
            self.items = old_items
            return False
