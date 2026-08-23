"""Tests for the ``AppStateStore`` base (shared/app_state.py).

Covers the projection contract (default ``app_state_keys`` + full-app
``project(app)`` override), app attachment via the existing
``attach_app_to_store`` machinery, the ``refresh`` RPC round-trip, server
authority over local state, the ``mutate()`` thread-safety guard, SSR
integration, client import-safety, and the store-subclass clobber guard.
"""

import json
import threading

from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.app_state import AppStateStore
from basis.shared.store import Store, attach_app_to_store


def _action_path(func) -> str:
    """The canonical registry path, mirroring how @server_action registers it."""
    return f"{func.__module__}.{func.__qualname__}"


def _cleanup(name: str):
    Store._store_blueprints.pop(name, None)
    Store._registry.pop(name, None)


# ── projection contract ────────────────────────────────────────────────────


def test_default_project_reads_app_state_keys():
    class BuildInfo(AppStateStore):
        app_state_keys = ("version", "feature_flags")

    app = Basis()
    app.state.version = "1.4.0"
    app.state.feature_flags = {"beta": True}

    store = BuildInfo("build_info")
    try:
        attach_app_to_store(store, app)
        assert store.version == "1.4.0"
        assert store.feature_flags == {"beta": True}
        assert store.serialize()["version"] == "1.4.0"
    finally:
        _cleanup("build_info")


def test_missing_app_state_key_projects_none():
    class BuildInfo(AppStateStore):
        app_state_keys = ("version", "missing")

    app = Basis()
    app.state.version = "1.4.0"
    store = BuildInfo("build_info_none")
    try:
        attach_app_to_store(store, app)
        assert store.version == "1.4.0"
        assert store.missing is None
    finally:
        _cleanup("build_info_none")


def test_project_override_full_app_access():
    class Status(AppStateStore):
        def project(self, app):
            return {
                "app_name": app.state.app_name,
                "plugin_count": len(app._plugin_registrations),
            }

    app = Basis()
    app.state.app_name = "jotter"
    store = Status("status_store")
    try:
        attach_app_to_store(store, app)
        assert store.app_name == "jotter"
        assert store.plugin_count == 0
    finally:
        _cleanup("status_store")


# ── app attachment & server authority ──────────────────────────────────────


def test_attach_app_refreshes_projection():
    class P(AppStateStore):
        app_state_keys = ("v",)

    app = Basis()
    app.state.v = 1
    store = P("p_refresh")
    try:
        attach_app_to_store(store, app)
        assert store.v == 1
        app.state.v = 2
        store._refresh_from_app()
        assert store.v == 2
    finally:
        _cleanup("p_refresh")


def test_server_projection_is_authoritative_over_local_state():
    class P(AppStateStore):
        app_state_keys = ("version",)

    app = Basis()
    app.state.version = "1.0"
    store = P("p_authority")
    try:
        attach_app_to_store(store, app)
        assert store.version == "1.0"
        # local (client-ish) mutation is overwritten by the server authority
        store.__dict__["version"] = "local"
        app.state.version = "2.0"
        store._refresh_from_app()
        assert store.version == "2.0"
    finally:
        _cleanup("p_authority")


def test_refresh_and_serialize_are_noop_without_app():
    """Client-side instance (no app): projection machinery must not raise."""
    class P(AppStateStore):
        app_state_keys = ("v",)

    store = P("p_no_app")
    try:
        assert store._refresh_from_app() is None
        state = store.serialize()
        assert "loading" in state  # base Store attrs only, no projection keys
        assert "v" not in state
    finally:
        _cleanup("p_no_app")


# ── refresh RPC round-trip ─────────────────────────────────────────────────


def test_refresh_rpc_round_trips_new_state():
    class CounterState(AppStateStore):
        app_state_keys = ("count",)

    app = Basis()
    app.state.count = 7
    CounterState("app_state_counter")
    app.bootstrap()
    try:
        client = TestClient(app)
        resp = client.post(
            "/basis/api/action",
            json={
                "path": _action_path(AppStateStore.refresh),
                "store_name": "app_state_counter",
                "args": [],
                "kwargs": {},
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] == {"ok": True}
        assert body["new_state"]["count"] == 7
    finally:
        _cleanup("app_state_counter")


# ── mutate() thread-safety guard ───────────────────────────────────────────


def test_mutate_serializes_concurrent_mutations():
    class P(AppStateStore):
        app_state_keys = ("counter",)

    app = Basis()
    app.state.counter = 0
    store = P("mutate_store")
    try:
        attach_app_to_store(store, app)

        results = []

        def worker():
            def bump():
                app.state.counter += 1
                return app.state.counter

            results.append(store.mutate(bump))

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert app.state.counter == 20
        assert sorted(results) == list(range(1, 21))
    finally:
        _cleanup("mutate_store")


# ── SSR integration ────────────────────────────────────────────────────────


def test_ssr_attach_and_serialize_projection():
    from basis.server.ssr import _get_all_stores, _serialize_initial_state

    app = Basis()
    app.state.version = "1.2.3"

    class BuildInfo(AppStateStore):
        app_state_keys = ("version",)

    store = BuildInfo("ssr_build_info")
    try:
        all_stores = _get_all_stores(
            None, None, stores={"ssr_build_info": store}, request_app=app
        )
        state = json.loads(_serialize_initial_state(all_stores))
        assert state["ssr_build_info"]["version"] == "1.2.3"
    finally:
        _cleanup("ssr_build_info")


# ── client import-safety ───────────────────────────────────────────────────


def test_app_state_module_is_client_safe():
    """The module must not import server-only code at module scope (Pyodide)."""
    import inspect

    from basis.shared import app_state as mod

    src = inspect.getsource(mod)
    assert "import fastapi" not in src
    assert "from fastapi" not in src
    assert "basis.server" not in src
    assert "import threading" in src  # stdlib only


# ── store-subclass clobber guard (documented pattern) ──────────────────────


def test_subclass_guard_pattern_preserves_hydrated_projection():
    class P(AppStateStore):
        def __init__(self, name):
            super().__init__(name)
            # the documented guard: never clobber an SSR-hydrated projection
            if not getattr(self, "_hydrated_from_ssr", False):
                self.__dict__["items"] = []

    store = P("guard_store")
    try:
        # server construction (not hydrated) → default applied
        assert store.__dict__["items"] == []

        # simulate the client: hydration already populated `items`
        store.__dict__["_hydrated_from_ssr"] = True
        store.__dict__["items"] = [1, 2, 3]
        # re-running the guarded init body would skip the default
        if not getattr(store, "_hydrated_from_ssr", False):
            store.__dict__["items"] = []
        assert store.__dict__["items"] == [1, 2, 3]
    finally:
        _cleanup("guard_store")


# ── registration via the EXISTING API (Phase 5 — no new API) ──────────────


def test_app_state_store_registered_via_app_include_store():
    """Registration via the existing ``app.include_store(name)``: the app-global
    SSR path collects the AppStateStore by blueprint, app-attaches it, and
    serializes the server projection."""
    from basis.server.ssr import _get_all_stores, _serialize_initial_state

    app = Basis()
    app.state.version = "3.0"

    class BuildInfo(AppStateStore):
        app_state_keys = ("version",)

    BuildInfo("include_store_build")  # blueprint (the module-scope convention)
    app.include_store("include_store_build")
    try:
        all_stores = _get_all_stores(
            None, None, global_stores=app._global_stores, request_app=app
        )
        state = json.loads(_serialize_initial_state(all_stores))
        assert state["include_store_build"]["version"] == "3.0"
    finally:
        _cleanup("include_store_build")


def test_app_state_store_registered_via_plugin_include_store():
    """Registration via the existing ``BasisPlugin.include_store(app, cls, name)``:
    constructs + app-attaches the AppStateStore, registers it in the registry and
    the app-global list, and its ``refresh`` RPC round-trips the projection."""
    from basis.server.plugin import BasisPlugin

    app = Basis()
    app.state.version = "4.2"

    class BuildInfo(AppStateStore):
        app_state_keys = ("version",)

    plugin = BasisPlugin(prefix="/x")
    plugin.include_store(app, BuildInfo, "plugin_build")
    app.bootstrap()
    try:
        store = Store._registry["plugin_build"]
        assert store.__dict__.get("_app") is app
        assert any(cfg.get("name") == "plugin_build" for cfg in app._global_stores)

        client = TestClient(app)
        resp = client.post(
            "/basis/api/action",
            json={
                "path": _action_path(AppStateStore.refresh),
                "store_name": "plugin_build",
                "args": [],
                "kwargs": {},
            },
        )
        assert resp.status_code == 200
        assert resp.json()["new_state"]["version"] == "4.2"
    finally:
        _cleanup("plugin_build")
