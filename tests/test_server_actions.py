"""
HTTP-level tests for the server-action RPC layer.

Store-bound ``@server_action`` methods must resolve even though the per-request
middleware wipes ``Store._registry``:

The fix:
  * ``Store._store_blueprints`` — a persistent (never per-request-cleared)
    blueprint registry; ``Store.reinstantiate(name)`` rebuilds a store from it.
  * The ``/basis/api/action`` endpoint is exempt from the middleware's
    registry reset.
  * The action handler falls back to ``Store.reinstantiate`` when the live
    instance is missing from the current request's registry.
"""
import asyncio
import logging

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.exceptions import HTTPException as StarletteHTTPException

from basis.server.app import Basis
from basis.server.plugin import BasisPlugin
from basis.shared.store import Store
from basis.shared.actions import server_action


# ---------------------------------------------------------------------------
# Test stores / functions (unique store names per class avoid blueprint collisions)
# ---------------------------------------------------------------------------

class CounterStore(Store):
    def __init__(self, name):
        super().__init__(name)
        self.count = 0

    @server_action
    def increment(self, by=1):
        self.count += by
        return self.count


class AsyncCounterStore(Store):
    def __init__(self, name):
        super().__init__(name)
        self.count = 0

    @server_action
    async def increment(self, by=1):
        await asyncio.sleep(0)  # ensure it is genuinely async
        self.count += by
        return self.count


class ArgStore(Store):
    """Store whose constructor takes extra args (ModelStore-style)."""

    def __init__(self, name, label, flag=True):
        super().__init__(name)
        self.label = label
        self.flag = flag
        self.hits = 0

    @server_action
    def hit(self):
        self.hits += 1
        return f"{self.label} hit {self.hits}"


class PluginTargetStore(Store):
    def __init__(self, name):
        super().__init__(name)
        self.total = 0


@server_action
def echo(value):
    return f"echo: {value}"


@server_action
def no_args():
    return "ok"


@server_action
def deny_fastapi():
    raise HTTPException(
        status_code=403, detail="denied", headers={"X-Reason": "policy"}
    )


@server_action
def deny_starlette():
    raise StarletteHTTPException(
        status_code=409, detail="conflict", headers={"X-Reason": "state"}
    )


@server_action
def disclose_secret():
    raise RuntimeError("sensitive-action-marker")


@server_action
async def cancel_action():
    raise asyncio.CancelledError


@pytest.fixture(autouse=True)
def _clean_registries():
    """Isolate tests: wipe the context registry and the persistent blueprints."""
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield
    Store._registry.clear()
    Store._store_blueprints.clear()


def _action_path(func) -> str:
    """The canonical registry path, mirroring how server_action registers it."""
    return f"{func.__module__}.{func.__qualname__}"


def _post_action(client, path, store_name=None, args=None, kwargs=None):
    return client.post(
        "/basis/api/action",
        json={
            "path": path,
            "store_name": store_name,
            "args": args or [],
            "kwargs": kwargs or {},
        },
    )


# ---------------------------------------------------------------------------
# Store-bound actions
# ---------------------------------------------------------------------------

def test_store_bound_sync_action_returns_data_and_new_state():
    app = Basis()
    store = CounterStore("counter")  # module-scope style registration
    app.bootstrap()
    client = TestClient(app)

    resp = _post_action(
        client, _action_path(CounterStore.increment), "counter", kwargs={"by": 2}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == 2
    assert body["new_state"]["count"] == 2
    # The live server-side singleton was used, not a copy
    assert store.count == 2


def test_store_singleton_state_persists_across_actions():
    app = Basis()
    CounterStore("counter")
    app.bootstrap()
    client = TestClient(app)

    for expected in (1, 2, 3):
        resp = _post_action(
            client, _action_path(CounterStore.increment), "counter", kwargs={"by": 1}
        )
        assert resp.status_code == 200
        assert resp.json()["data"] == expected


def test_store_bound_async_action():
    app = Basis()
    AsyncCounterStore("async_counter")
    app.bootstrap()
    client = TestClient(app)

    resp = _post_action(
        client,
        _action_path(AsyncCounterStore.increment),
        "async_counter",
        kwargs={"by": 5},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == 5
    assert body["new_state"]["count"] == 5


def test_store_action_works_after_registry_reset():
    """
    Regression for Critical #1: when the live instance is missing from the
    registry (e.g. the per-request middleware reset destroyed it, or a fresh
    worker process), the action must still succeed by falling back to the
    persistent blueprint registry.
    """
    app = Basis()
    CounterStore("counter")
    app.bootstrap()
    client = TestClient(app)

    # Simulate a reset that wiped the live instance from the server context
    Store._registry.clear()
    assert "counter" not in Store._registry
    assert "counter" in Store._store_blueprints  # blueprint survives

    resp = _post_action(
        client, _action_path(CounterStore.increment), "counter", kwargs={"by": 1}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == 1  # fresh instance rebuilt from the blueprint
    assert body["new_state"]["count"] == 1


def test_store_with_extra_constructor_args_is_rebuilt():
    """Blueprint re-instantiation must preserve constructor args/kwargs."""
    app = Basis()
    ArgStore("arg_store", "My Label", flag=False)
    app.bootstrap()
    client = TestClient(app)

    # Force a registry reset so the action must rebuild from the blueprint
    Store._registry.clear()

    resp = _post_action(client, _action_path(ArgStore.hit), "arg_store")
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == "My Label hit 1"
    assert body["new_state"]["label"] == "My Label"
    assert body["new_state"]["flag"] is False


def test_store_action_with_vfs_path_rewrite():
    """
    The action handler maps a client VFS module path back to the server module
    using the bootstrap-time ``vfs_to_server_module`` registry.
    """
    app = Basis()
    CounterStore("counter")
    app.bootstrap()

    # Simulate the live VFS registry populated at startup
    app.vfs.vfs_to_server_module = {"myapp": echo.__module__}

    client = TestClient(app)
    resp = _post_action(
        client, "myapp.CounterStore.increment", "counter", kwargs={"by": 3}
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == 3


# ---------------------------------------------------------------------------
# Stateless (function) actions
# ---------------------------------------------------------------------------

def test_stateless_function_action():
    app = Basis()
    app.bootstrap()
    client = TestClient(app)

    resp = _post_action(client, _action_path(echo), kwargs={"value": "hi"})
    assert resp.status_code == 200
    # No store -> no new_state key
    assert resp.json() == {"data": "echo: hi"}


# ---------------------------------------------------------------------------
# Plugin actions bound to a store
# ---------------------------------------------------------------------------

def test_plugin_action_bound_to_store():
    app = Basis()
    PluginTargetStore("plugin_target")
    app.bootstrap()

    plugin = BasisPlugin(prefix="/p", name="p")

    @plugin.action
    def accumulate(store, amount=1):
        store.total += amount
        return store.total

    app.include_plugin(plugin)
    client = TestClient(app)

    resp = client.post(
        "/basis/api/action",
        json={
            "path": _action_path(accumulate),
            "action_name": "accumulate",
            "plugin_name": "p",
            "store_name": "plugin_target",
            "args": [],
            "kwargs": {"amount": 4},
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["data"] == 4
    assert body["new_state"]["total"] == 4


def test_plugin_action_bound_to_store_after_registry_reset():
    app = Basis()
    PluginTargetStore("plugin_target")
    app.bootstrap()

    plugin = BasisPlugin(prefix="/p", name="p")

    @plugin.action
    def accumulate(store, amount=1):
        store.total += amount
        return store.total

    app.include_plugin(plugin)
    client = TestClient(app)

    client.get("/basis/api/plugins")  # trigger registry reset

    resp = client.post(
        "/basis/api/action",
        json={
            "path": _action_path(accumulate),
            "action_name": "accumulate",
            "plugin_name": "p",
            "store_name": "plugin_target",
            "args": [],
            "kwargs": {"amount": 7},
        },
    )
    assert resp.status_code == 200
    assert resp.json()["data"] == 7


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_unknown_store_returns_404():
    app = Basis()
    CounterStore("counter")
    app.bootstrap()
    client = TestClient(app)

    resp = _post_action(
        client, _action_path(CounterStore.increment), "does_not_exist"
    )
    assert resp.status_code == 404
    assert "Store 'does_not_exist' not found" in resp.text


def test_unknown_action_returns_404():
    app = Basis()
    CounterStore("counter")
    app.bootstrap()
    client = TestClient(app)

    resp = _post_action(client, "no.such.Module.nothing", "counter")
    assert resp.status_code == 404
    assert "Action 'no.such.Module.nothing' not found" in resp.text


def test_invalid_json_payload_returns_400():
    app = Basis()
    app.bootstrap()
    client = TestClient(app)

    resp = client.post("/basis/api/action", content=b"not-json", headers={"content-type": "application/json"})
    assert resp.status_code == 400
    assert "Invalid JSON payload" in resp.text


@pytest.mark.parametrize(
    ("payload", "field"),
    [
        (None, "payload"),
        ([], "payload"),
        ("action", "payload"),
        (1, "payload"),
        (True, "payload"),
        ({}, "path"),
        ({"path": None}, "path"),
        ({"path": 1}, "path"),
        ({"path": ""}, "path"),
        ({"path": "   "}, "path"),
        ({"path": _action_path(no_args), "store_name": ""}, "store_name"),
        ({"path": _action_path(no_args), "store_name": []}, "store_name"),
        ({"path": _action_path(no_args), "args": None}, "args"),
        ({"path": _action_path(no_args), "args": {}}, "args"),
        ({"path": _action_path(no_args), "kwargs": None}, "kwargs"),
        ({"path": _action_path(no_args), "kwargs": []}, "kwargs"),
        ({"path": _action_path(no_args), "action_name": 1}, "action_name"),
        ({"path": _action_path(no_args), "plugin_name": []}, "plugin_name"),
    ],
)
def test_invalid_rpc_envelope_returns_400_without_dispatch(
    monkeypatch, payload, field
):
    invoked = False

    async def fake_run_action(func, instance, args, kwargs):
        nonlocal invoked
        invoked = True

    monkeypatch.setattr("basis.server.rpc._run_action", fake_run_action)
    app = Basis()
    app.bootstrap()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/basis/api/action", json=payload)

    assert response.status_code == 400
    assert field in response.text
    assert invoked is False


def test_minimal_rpc_envelope_uses_default_arguments():
    app = Basis()
    app.bootstrap()
    client = TestClient(app)

    response = client.post(
        "/basis/api/action", json={"path": _action_path(no_args), "extra": "ignored"}
    )

    assert response.status_code == 200
    assert response.json() == {"data": "ok"}


@pytest.mark.parametrize(
    ("action", "status", "detail", "reason"),
    [
        (deny_fastapi, 403, "denied", "policy"),
        (deny_starlette, 409, "conflict", "state"),
    ],
)
def test_intentional_http_errors_are_preserved(action, status, detail, reason):
    app = Basis()
    app.bootstrap()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/basis/api/action", json={"path": _action_path(action)})

    assert response.status_code == status
    assert response.json() == {"detail": detail}
    assert response.headers["X-Reason"] == reason


def test_unexpected_action_error_is_logged_and_sanitized(caplog):
    app = Basis()
    app.bootstrap()
    client = TestClient(app, raise_server_exceptions=False)

    with caplog.at_level(logging.ERROR, logger="uvicorn.error"):
        response = client.post(
            "/basis/api/action", json={"path": _action_path(disclose_secret)}
        )

    assert response.status_code == 500
    assert response.json() == {"detail": "Server action failed"}
    assert "sensitive-action-marker" not in response.text
    assert "sensitive-action-marker" in caplog.text


def test_unexpected_response_error_is_sanitized(monkeypatch):
    def fail_response(result, instance):
        raise RuntimeError("sensitive-response-marker")

    monkeypatch.setattr("basis.server.rpc._rpc_response", fail_response)
    app = Basis()
    app.bootstrap()
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post("/basis/api/action", json={"path": _action_path(no_args)})

    assert response.status_code == 500
    assert response.json() == {"detail": "Server action failed"}
    assert "sensitive-response-marker" not in response.text


def test_action_cancellation_propagates():
    from basis.server.rpc import _handle_action

    class Request:
        async def json(self):
            return {"path": _action_path(cancel_action)}

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(_handle_action(Basis(), Request()))


# ---------------------------------------------------------------------------
# Blueprint registry unit behavior
# ---------------------------------------------------------------------------

def test_conflicting_redeclaration_raises():
    """
    Same name + a DIFFERENT factory is a genuine ``$name`` ambiguity and must fail
    loudly — this replaces the old silent "first declaration wins" behaviour.
    """
    CounterStore("conflict_counter")

    # Different class, same name -> conflict
    with pytest.raises(ValueError, match="already registered"):
        Store("conflict_counter")

    # Same class, different constructor args -> conflict
    with pytest.raises(ValueError, match="already registered"):
        ArgStore("conflict_counter", "Different Label")

    # The canonical blueprint is untouched by the failed attempts
    revived = Store.reinstantiate("conflict_counter")
    assert isinstance(revived, CounterStore)
    assert revived.count == 0


def test_reinstantiation_same_factory_is_benign():
    """Reconstructing the SAME factory under an existing name is legal (RPC/SSR)."""
    counter = CounterStore("benign_counter")

    # Same class + args, direct reconstruction -> must NOT raise
    again = CounterStore("benign_counter")
    assert again is not counter
    assert again.count == 0

    # The RPC/SSR reconstruction path is unaffected
    revived = Store.reinstantiate("benign_counter")
    assert isinstance(revived, CounterStore)


def test_reinstantiate_returns_none_for_missing_blueprint():
    assert Store.reinstantiate("missing_store") is None


def test_blueprint_survives_registry_clear():
    CounterStore("bp2_counter")
    assert "bp2_counter" in Store._registry
    assert "bp2_counter" in Store._store_blueprints

    Store._registry.clear()
    assert "bp2_counter" not in Store._registry
    assert "bp2_counter" in Store._store_blueprints

    revived = Store.reinstantiate("bp2_counter")
    assert isinstance(revived, CounterStore)
