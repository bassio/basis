import dataclasses
import inspect
import json
import sys
from collections.abc import Mapping
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
        from pyscript import WebSocket
        from pyodide.http import pyfetch
    except ImportError:
        WebSocket = None
        pyfetch = None
else:
    WebSocket = None
    pyfetch = None

from basis.shared.context import ContextVarProxyDict
from basis.shared.events import BrowserMixin
from basis.shared.reactive import ReactiveObject, batch, state
from basis.shared.serialization import snapshot_jsonable


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


def attach_app_to_store(store, app) -> None:
    """Attach the owning app to an app-bound store (``_requires_app``) and
    refresh its derived state (e.g. the ``$plugins`` listing).

    No-op for stores that don't opt in (no ``_requires_app``) or already have
    the app attached. Shared by the SSR/CSR serializers and both RPC handlers so
    every store-rebuild path (including ``Store.resolve`` reinstantiation) keeps
    ``_app`` in sync before ``serialize()``/listing is read.
    """
    if store is None or app is None:
        return
    if getattr(type(store), "_requires_app", False) and getattr(store, "_app", None) is None:
        store.__dict__["_app"] = app
        refresh = getattr(store, "_refresh_from_app", None)
        if refresh is not None:
            refresh()


async def run_apply_request(store, request) -> None:
    """Run *store*'s ``apply_request(request)`` hook, if it defines one.

    The hook is how a store reads request-scoped state before anything is
    rendered or serialized (``$theme`` reads its ``basis_theme`` cookie; a
    session store resolves its session cookie). It may be sync or async. A hook
    that raises is ignored — a broken request read must not take down the page or
    the action.
    """
    apply_request = getattr(store, "apply_request", None)
    if not callable(apply_request):
        return
    try:
        if inspect.iscoroutinefunction(apply_request):
            await apply_request(request)
        else:
            apply_request(request)
    except Exception:
        pass


# Framework-provided control-plane stores. These are always serialized into
# ``#basis-initial-state`` so they hydrate on every page — on SSR they are added
# to the app's ``_global_stores``; on CSR they are unioned into the page's
# serialized set regardless of the page's ``Page.stores`` subset.
#
# ``$head`` (document head, MOBILE-M1.1) is a Page-level default exactly like
# ``$plugins``: the Page guarantees the store exists (empty by default) and the
# base template's head loops bind its ``metas``/``links`` lists. Plugins and
# components never ``include_store`` it — they only push items into it.
#
# ``$device`` / ``$network`` (MOBILE-M1.3) are Page-level defaults too: the
# client-observed context data plane, serialized with neutral defaults on the
# server so SSR and CSR first paint agree (the client probes real values after
# mount).
# NOTE: ``$regions`` is NOT here — it is provided by the official regions plugin
# (basis.plugins.regions), which registers its store at boot so it is picked up
# by the default "all stores" serialization path.
FRAMEWORK_STORE_NAMES = ("plugins", "head", "device", "network")


def ensure_store(name: str, store_cls: type) -> Store:
    """Return the live store registered under *name*, creating it if absent.

    The generic "ensure this store exists" primitive behind
    ``ensure_plugin_registry`` (and ``ensure_region_registry`` in the regions
    plugin). Idempotent: an existing instance in ``Store._registry`` is
    returned as-is.
    """
    existing = Store._registry.get(name)
    if existing is not None:
        return existing
    return store_cls(name)


# Set by the client entrypoint once every page has mounted. A store built after that
# point must attach its own client listeners, because the ready sweep has already run.
# Never set on the server, where the entrypoint does not execute.
_client_ready = False
_NO_INITIAL_STATE = object()


@dataclasses.dataclass(frozen=True)
class _InitialStateClaim:
    name: str
    values: Any
    metadata: Mapping[str, Any]


@dataclasses.dataclass
class _InitialLoadProvenance:
    snapshot_applied: bool
    url: Any = None
    params: Mapping[str, Any] | None = None
    fetch_consumed: bool = False


class _InitialStateOwner:
    def __init__(self) -> None:
        self.install({})

    def install(self, payload: Mapping[str, Any]) -> None:
        if not isinstance(payload, Mapping):
            raise ValueError("Initial state must be a mapping")
        self._payload = dict(payload)
        metadata = self._payload.get("__basis_meta__", {})
        self._metadata = metadata if isinstance(metadata, Mapping) else {}
        self._claimed: set[str] = set()
        self._consumed: set[str] = set()

    def claim(self, name: str) -> _InitialStateClaim | None:
        if name not in self._payload or name in self._claimed or name in self._consumed:
            return None
        self._claimed.add(name)
        metadata = {}
        ssr_params = self._metadata.get("ssr_params", {})
        if isinstance(ssr_params, Mapping) and name in ssr_params:
            metadata["_ssr_params"] = ssr_params[name]
        ssr_url = self._metadata.get("ssr_url", {})
        if isinstance(ssr_url, Mapping) and name in ssr_url:
            metadata["_ssr_url"] = ssr_url[name]
        return _InitialStateClaim(name, self._payload[name], metadata)

    def commit(self, claim: _InitialStateClaim) -> None:
        self._claimed.discard(claim.name)
        self._consumed.add(claim.name)

    def release(self, claim: _InitialStateClaim) -> None:
        self._claimed.discard(claim.name)

    def discard(self, name: str) -> None:
        self._claimed.discard(name)
        if name in self._payload:
            self._consumed.add(name)


_initial_state_owner = _InitialStateOwner()


def install_initial_state(payload: Mapping[str, Any]) -> None:
    """Install the parsed initial-state payload for the current client boot."""
    _initial_state_owner.install(payload)


def mark_client_ready() -> None:
    """Record that the client document has mounted (client entrypoint only)."""
    global _client_ready
    _client_ready = True


class StoreMeta(type):
    def __call__(cls, *args, _initial_state=_NO_INITIAL_STATE, **kwargs):
        instance = super().__call__(*args, **kwargs)
        name = instance.__dict__.get("_name")
        if name is None:
            raise TypeError(f"{cls.__name__}.__init__() must initialize the store name")

        config_kwargs = dict(kwargs)
        config_kwargs.pop("name", None)
        config_args = args[1:] if args else ()
        config = cls._capture_config(*config_args, **config_kwargs)
        instance._finish_construction(config, initial_state=_initial_state)
        return instance


class Store(BrowserMixin, ReactiveObject, metaclass=StoreMeta):
    loading = False
    error = None

    _registry = ContextVarProxyDict("store_registry")
    _pending_subscriptions = ContextVarProxyDict("store_pending_subscriptions")

    # Persistent config registry: name -> (cls, config_snapshot).
    # Unlike `_registry` (which is cleared per-request for SSR isolation), this is a plain
    # class-level dict that survives request boundaries, so server actions can re-instantiate
    # a store even after the per-request registry reset wiped the live instance.
    _store_blueprints: dict[str, tuple[type, dict]] = {}

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        if "__new__" in cls.__dict__:
            raise TypeError(
                f"{cls.__name__} cannot define __new__; Store construction is finalized "
                "after __init__"
            )

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
        Return the active store by name, reconstructing its canonical blueprint
        only when the current context has no active instance.
        """
        active = cls._registry.get(name)
        if active is not None:
            return active
        restored = cls.reinstantiate(name)
        if restored is None:
            raise KeyError(f"No store named '{name}' has been declared")
        return restored

    @classmethod
    def from_dict(cls, name:str, init_dict:dict):
        return cls(name, _initial_state=init_dict)

    def __init__(self, name: str):
        super().__init__()
        self.__dict__['_subscriptions'] = []
        self.__dict__['_name'] = name
        self.__dict__['_initial_load'] = None
        self.__dict__['_first_load_completed'] = False

    def _finish_construction(self, config: dict, *, initial_state=_NO_INITIAL_STATE) -> None:
        name = self.get_store_name()
        blueprint = self._validated_blueprint(name, config)
        claim = None if initial_state is not _NO_INITIAL_STATE else _initial_state_owner.claim(name)
        values = initial_state if initial_state is not _NO_INITIAL_STATE else (
            claim.values if claim is not None else _NO_INITIAL_STATE
        )

        try:
            if values is not _NO_INITIAL_STATE:
                if not isinstance(values, Mapping):
                    raise ValueError(f"Store '{name}' state must be a mapping")
                self.apply_state(values)
                self.__dict__['_first_load_completed'] = True
            if claim is not None:
                self.__dict__['_initial_load'] = _InitialLoadProvenance(
                    snapshot_applied=True,
                    url=claim.metadata.get("_ssr_url"),
                    params=claim.metadata.get("_ssr_params"),
                )

            self._validate_required_state()
            self._init_computed(prime=False)

            displaced = Store._registry.get(name)
            Store._store_blueprints[name] = blueprint
            Store._registry[name] = self
            if claim is not None:
                _initial_state_owner.commit(claim)
            elif initial_state is not _NO_INITIAL_STATE:
                _initial_state_owner.discard(name)
        except Exception:
            if claim is not None:
                _initial_state_owner.release(claim)
            raise

        if displaced is not None and displaced is not self:
            displaced.on_client_teardown()

        self._prime_computed()
        self._deliver_pending_subscriptions()
        if _client_ready:
            self.on_client_ready()

    def _consume_initial_fetch(self, *, url=None, params=None) -> bool:
        provenance = self.__dict__.get("_initial_load")
        if provenance is None or provenance.fetch_consumed:
            return False
        if url is not None:
            matches = provenance.url == url
        elif params is not None and provenance.params is not None:
            matches = all(
                key in provenance.params and str(provenance.params[key]) == str(value)
                for key, value in params.items()
            )
        else:
            matches = False
        if not matches:
            return False
        provenance.fetch_consumed = True
        return True

    def _validated_blueprint(self, name: str, config: dict) -> tuple[type, dict]:
        existing = Store._store_blueprints.get(name)
        if existing is None:
            return type(self), config
        store_cls, store_config = existing
        if store_cls is type(self) and store_config == config:
            return existing
        raise ValueError(
            f"Cannot redeclare store '{name}': already registered as "
            f"{store_cls.__name__}{_format_config(store_config)}, attempting to "
            f"register as {type(self).__name__}{_format_config(config)}. Store "
            "names are unique (they are the $<name> DSL identity)."
        )

    def _deliver_pending_subscriptions(self) -> None:
        name = self.get_store_name()
        for component, attr_name in Store._pending_subscriptions.pop(name, ()):
            self.add_subscription(
                component,
                attr_name,
                scope=getattr(component, "_scope", None),
            )
            subscribed_field = f"${name}.{attr_name}" if attr_name else f"${name}"
            with component.refrain() as refrained:
                value = getattr(self, attr_name, None) if attr_name else self
                setattr(refrained, subscribed_field, value)

    def serialize(self) -> dict:
        """Return a detached, strictly JSON-compatible state snapshot."""
        snapshot = {}
        store_path = f"Store '{self.get_store_name()}'"
        for name in self._state_fields:
            spec = self._state_specs.get(name)
            if spec is not None and not spec.serialize:
                continue
            snapshot[name] = snapshot_jsonable(
                self.__dict__[name],
                path=f"{store_path}.{name}",
            )
        return snapshot

    def get_store_name(self):
        return self.__dict__['_name']

    def add_subscription(self, component_instance, attr_name:str, scope=None):
        if (component_instance, attr_name) in self._subscriptions:
            return
        # Dedup bookkeeping only — the reactive edge is the DAG effect below.
        self.__dict__['_subscriptions'].append((component_instance, attr_name))

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

        if scope is not None:
            scope.record_effect(self._dag, effect_name)
            scope.record_cleanup(
                lambda: self.remove_subscription(component_instance, attr_name)
            )

    def remove_subscription(self, component_instance, attr_name:str):
        self.__dict__['_subscriptions'] = [
            sub for sub in self._subscriptions if sub != (component_instance, attr_name)
        ]
        effect_name = f"sub_{id(component_instance)}_{attr_name}"
        self._dag.remove_node(effect_name)

    def on_client_ready(self) -> None:
        """Client-only: the document has mounted; attach client-side listeners here.

        The declarations attach here rather than at construction because a subscriber's first
        write is an ordinary DAG update only once the SSR document has been adopted.
        Overriders must call ``super().on_client_ready()``.
        """
        super().on_client_ready()

    def on_client_teardown(self) -> None:
        """Client-only: undo :meth:`on_client_ready`. Safe to call repeatedly."""
        super().on_client_teardown()

    def _require_app(self):
        """Return the owning app for an app-bound store (``_requires_app``).

        The RPC layer attaches ``_app`` before dispatching to an app-bound store
        (``attach_app_to_store``), so client-facing server actions can rely on
        this being present server-side.
        """
        app = self.__dict__.get("_app")
        if app is None:
            raise RuntimeError(
                f"{type(self).__name__} requires the owning Basis app "
                "(server-side). Perform the mutation on the server directly."
            )
        return app

    def _prepare_state(self, values: Mapping) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            raise ValueError(
                f"Store '{self.get_store_name()}' state must be a mapping"
            )

        prepared = {}
        for name, value in values.items():
            self._validate_state_key(name)
            prepared[name] = self._prepare_state_value(name, value)
        return prepared

    def _validate_state_key(self, name: object) -> None:
        if not isinstance(name, str) or not name.isidentifier() or name.startswith("_"):
            raise ValueError(
                f"Store '{self.get_store_name()}' has invalid state field {name!r}"
            )

        spec = self._state_specs.get(name)
        if spec is not None:
            if not spec.serialize:
                raise ValueError(
                    f"Store '{self.get_store_name()}' field '{name}' is local-only"
                )
            return

        missing = object()
        class_member = inspect.getattr_static(type(self), name, missing)
        if class_member is not missing:
            raise ValueError(
                f"Store '{self.get_store_name()}' field '{name}' collides with "
                "class configuration or behavior"
            )

    def _prepare_state_value(self, name: str, value: Any) -> Any:
        return value

    def apply_state(self, new_state: Mapping) -> None:
        """Validate and apply a partial state snapshot as one reactive batch."""
        prepared = self._prepare_state(new_state)
        with batch():
            for key, value in prepared.items():
                setattr(self, key, value)

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

    def on_client_ready(self) -> None:
        super().on_client_ready()
        if WebSocket and self.__dict__.get('_ws') is None:
            self.__dict__['_ws'] = WebSocket.new(self.ws_url)
            self.__dict__['_ws'].onmessage = self._on_message

    def on_client_teardown(self) -> None:
        super().on_client_teardown()
        websocket = self.__dict__.pop('_ws', None)
        if websocket is not None:
            websocket.close()
        self.__dict__['_ws'] = None

    @property
    def ws_url(self) -> str:
        return self.__dict__['_config']['ws_url']

    @property
    def ws(self):
        return self.__dict__.get('_ws')
    
    def _on_message(self, event):
        data = json.loads(event.data)
        self.apply_state(data)

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
    items: list = state(default_factory=list)

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

    def _prepare_state_value(self, name: str, value: Any) -> Any:
        if name != "items":
            return super()._prepare_state_value(name, value)
        if not isinstance(value, (list, tuple)):
            raise ValueError(
                f"Store '{self.get_store_name()}' field 'items' must be a list"
            )

        validate = getattr(self.model, "model_validate", None)
        if validate is None:
            return ReactiveCollection(value)

        prepared = []
        for index, item in enumerate(value):
            if isinstance(item, self.model):
                prepared.append(item)
                continue
            try:
                prepared.append(validate(item))
            except Exception as exc:
                raise ValueError(
                    f"Store '{self.get_store_name()}' has invalid state at "
                    f"items[{index}]"
                ) from exc
        return ReactiveCollection(prepared)

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
                self.apply_state({"items": list(session.exec(statement).all())})
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
                self.apply_state({"items": data, "error": None})
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

        if _is_server():
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
                self.apply_state({
                    key: value
                    for key, value in item.__dict__.items()
                    if not key.startswith("_")
                })
            return item


        self.loading = True

        try:
            pf = _get_pyfetch()
            response = await pf(resolved_url)
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
                    new_items = self.items + [item]

                item_values = item.__dict__ if hasattr(item, "__dict__") else item
                self.apply_state({
                    "items": new_items,
                    "error": None,
                    **{
                        key: value
                        for key, value in item_values.items()
                        if not key.startswith("_")
                    },
                })
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

        if _is_server():
            return temp_item

        self.__dict__["loading"] = True

        try:
            pf = _get_pyfetch()
            response = await pf(
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
