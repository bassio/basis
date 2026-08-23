"""Server-authoritative app state projected to all clients — the ``AppStateStore`` base.

An ``AppStateStore`` is a :class:`~basis.shared.store.Store` whose state is a
*reactive, JSON-safe projection* of authoritative state owned by the server app
process (FastAPI ``app.state`` by default, or anywhere on the app object via a
``project()`` override). It formalizes what ``$plugins`` and ``$regions`` do ad
hoc:

* the server owns the data — the store is a projection, never the source of truth,
* the same data is broadcast to every client,
* the state lives as long as the process (a restart re-projects from ``app.state``),
* the client is a hydrated reactive view that can re-pull via ``refresh()``.

The module lives in ``shared/`` so the same class is importable on the client
(Pyodide) — ``project()`` is pure server code, but the module must not import
fastapi/server modules at module scope.

Full design: APP-STATE-STORES.md (app access §5, concurrency §6, serialization
§7 via ``shared/serialization.py``, refresh §8; push/StateHub deferred to a
later phase).
"""

from __future__ import annotations

import threading
from typing import Any, Callable

from basis.shared.actions import server_action
from basis.shared.serialization import jsonable
from basis.shared.store import Store


class AppStateStore(Store):
    """Server-authoritative app state projected to all clients.

    App-bound via ``_requires_app`` (the existing attach machinery): SSR/CSR
    serializers and the RPC handler call ``attach_app_to_store`` which sets
    ``_app`` and runs :meth:`_refresh_from_app` before ``serialize()``/actions.

    Default data source: project the declared ``app_state_keys`` from
    ``app.state``. Override :meth:`project` for full app access (read
    ``app._plugin_registrations``, ``app._regions``, call app methods, ...).
    """

    _requires_app = True

    #: Default source: project these keys from ``app.state`` (a missing key → None).
    app_state_keys: tuple[str, ...] = ()

    # ── the projection boundary (the ONLY thing that crosses the wire) ──
    def project(self, app) -> dict:
        """Return a JSON-safe dict that becomes this store's reactive state.

        Default: project the declared ``app_state_keys`` from ``app.state``.
        Override to access the whole app object freely. The returned dict keys
        become store attributes; values are projected via
        :func:`~basis.shared.serialization.jsonable` so raw app objects never
        cross the wire.
        """
        return {
            k: jsonable(getattr(app.state, k, None))
            for k in self.app_state_keys
        }

    # ── server-side machinery (inherit; override rarely) ─────────────────
    def _refresh_from_app(self) -> None:
        """Recompute the projection from the app (no-op without an app).

        Server-side projection writes go through ``__dict__`` (no subscribers
        server-side); the client hydrates reactively via ``#basis-initial-state``
        / ``store.update(new_state)``.
        """
        app = self.__dict__.get("_app")
        if app is None:
            return
        for k, v in self.project(app).items():
            self.__dict__[k] = v

    def serialize(self) -> dict:
        self._refresh_from_app()
        return super().serialize()

    # ── pull (on-demand re-sync) ─────────────────────────────────────────
    @server_action
    async def refresh(self) -> dict:
        """Pull the latest projection from the server (client RPC).

        The RPC layer re-applies ``new_state`` to the client store via
        ``store.update()``, so subscribers re-render reactively. (Push via a
        StateHub is deferred — APP-STATE-STORES.md §8.)
        """
        self._refresh_from_app()
        return {"ok": True}

    # ── mutation guard (thread-safety, §6.1) ─────────────────────────────
    def mutate(self, fn: Callable[[], Any]) -> Any:
        """Run *fn* while holding this store's mutation lock.

        Serializes sync threadpool handlers, background threads, and event-loop
        code that mutate the authoritative app state. Keep the critical section
        short and synchronous — do not ``await`` while holding the lock (a
        blocking acquire on the loop would stall the server).
        """
        lock = self.__dict__.get("_mutex")
        if lock is None:
            lock = threading.Lock()
            self.__dict__["_mutex"] = lock
        with lock:
            return fn()
