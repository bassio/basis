"""The in-flight request is reachable from plugin code via ``current_request()``.

Bound for the whole page render (both engines) and for the whole server-action
dispatch, and released afterwards so nothing downstream observes a stale request.
"""

import asyncio
from types import SimpleNamespace

from basis.server.app import Basis
from basis.server.render import render_page
from basis.server.rpc import make_action_handler
from basis.shared.actions import _action_registry, server_action
from basis.shared.component import Component
from basis.shared.context import current_request, request_var
from basis.shared.page import Page
from basis.shared.store import Store

_seen = {}


@server_action
async def _record_request() -> dict:
    _seen["request"] = current_request()
    return {"ok": True}


class RequestProbeStore(Store):
    """Records what the render pipeline made reachable to a store hook."""

    hook_saw_request = False

    def apply_request(self, request):
        _seen["hook_request"] = current_request()
        _seen["hook_is_same"] = current_request() is request
        self.hook_saw_request = current_request() is request


def _build_app():
    RequestProbeStore("request_probe")

    class Root(Component):
        template = "<div>root</div>"

    class ProbePage(Page):
        title = "probe"
        root_component = Root
        stores = ["request_probe"]

    app = Basis()
    app.bootstrap()
    return app, ProbePage


def test_current_request_is_none_outside_a_request():
    assert current_request() is None
    assert request_var.get() is None


def test_render_binds_request_for_store_hooks_and_releases_it():
    for mode in ("ssr", "csr"):
        app, page = _build_app()
        _seen.clear()

        async def _run():
            fake_request = SimpleNamespace(app=app)
            await render_page(fake_request, page, render_mode=mode)
            return current_request()

        # ``None`` after the render proves the binding was released; the store
        # hook asserts, from inside the pipeline, that it saw this same request.
        assert asyncio.run(_run()) is None, mode
        assert _seen["hook_is_same"] is True, mode


def test_action_dispatch_binds_request_for_the_body_and_releases_it():
    app, _ = _build_app()
    _seen.clear()

    path = next(p for p in _action_registry if p.endswith("._record_request"))

    class FakeRequest:
        """Just enough request for the RPC dispatch (it only reads ``.json()``)."""

        def __init__(self, app, payload):
            self.app = app
            self._payload = payload

        async def json(self):
            return self._payload

    async def _run():
        handler = make_action_handler(app)
        response = await handler(
            FakeRequest(app, {"path": path, "args": [], "kwargs": {}})
        )
        return response, current_request()

    response, after = asyncio.run(_run())
    assert response.status_code == 200
    # The action body saw the very request that was dispatched...
    assert _seen["request"] is not None
    # ...and the binding was released once the dispatch finished.
    assert after is None
