"""SSR and CSR render through one pipeline.

Both engines collect the same stores, bind the request's database session
*before* per-request hooks run, and serialize through the same funnel — so a
store's request-time projection cannot depend on the render mode. The store
shape exercised here is the one a DB-backed session store needs (an
``apply_request`` hook that queries the database).
"""

import asyncio
import json
import re

from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, SQLModel, Session, create_engine, select

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.context import db_session_var
from basis.shared.page import Page
from basis.shared.store import Store

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)


class Probe(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    value: str = "from-db"


def get_session():
    with Session(engine) as session:
        yield session


class DbProbeStore(Store):
    """Queries the database from ``apply_request`` — the auth-store shape."""

    saw_session = False
    db_value = ""

    def apply_request(self, request):
        session = db_session_var.get()
        self.saw_session = session is not None
        if session is None:
            return
        row = session.exec(select(Probe)).first()
        self.db_value = row.value if row else ""


class AsyncProbeStore(Store):
    """An async hook must be awaited, not silently dropped."""

    visited = False

    async def apply_request(self, request):
        await asyncio.sleep(0)
        self.visited = True


def _build_app():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.exec(select(Probe)).first() is None:
            session.add(Probe(value="from-db"))
            session.commit()

    # Construct once so the blueprint registry can rebuild them per request —
    # the middleware clears the live registry at the start of every request.
    DbProbeStore("db_probe")
    AsyncProbeStore("async_probe")

    class Root(Component):
        template = "<div>root</div>"

    class ProbePage(Page):
        title = "probe"
        root_component = Root
        stores = ["db_probe", "async_probe"]

    app = Basis()
    app.get_session = get_session
    app.bootstrap()

    from basis.server.responses import PageResponse

    @app.get("/probe-ssr")
    async def ssr(request: Request):
        return await PageResponse.from_page(ProbePage, request, render_mode="ssr")

    @app.get("/probe-csr")
    async def csr(request: Request):
        return await PageResponse.from_page(ProbePage, request, render_mode="csr")

    return app


def _state(html):
    match = re.search(
        r'<script id="basis-initial-state"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    assert match, "basis-initial-state script not found"
    return json.loads(match.group(1))


def test_csr_binds_db_session_before_request_hooks():
    client = TestClient(_build_app())
    state = _state(client.get("/probe-csr").text)
    assert state["db_probe"]["saw_session"] is True
    assert state["db_probe"]["db_value"] == "from-db"


def test_ssr_binds_db_session_before_request_hooks():
    client = TestClient(_build_app())
    state = _state(client.get("/probe-ssr").text)
    assert state["db_probe"]["saw_session"] is True
    assert state["db_probe"]["db_value"] == "from-db"


def test_async_apply_request_hook_runs_on_both_engines():
    client = TestClient(_build_app())
    assert _state(client.get("/probe-ssr").text)["async_probe"]["visited"] is True
    assert _state(client.get("/probe-csr").text)["async_probe"]["visited"] is True


def test_engines_serialize_identical_store_state():
    client = TestClient(_build_app())
    ssr = _state(client.get("/probe-ssr").text)
    csr = _state(client.get("/probe-csr").text)

    assert ssr["db_probe"] == csr["db_probe"]
    assert ssr["async_probe"] == csr["async_probe"]

    # Framework control-plane stores hydrate on every page, whichever engine
    # serves it — including pages that declare a strict store subset.
    assert "plugins" in ssr and "plugins" in csr
    # ...but a plugin-provided store is not force-serialized for a strict subset.
    assert "regions" not in ssr and "regions" not in csr


def test_apply_request_failure_does_not_break_the_render():
    """A raising hook leaves the store at its default; the page still serves."""

    class BoomStore(Store):
        reached = False

        def apply_request(self, request):
            self.reached = True
            raise RuntimeError("hook exploded")

    BoomStore("boom_probe")

    class Root(Component):
        template = "<div>root</div>"

    class BoomPage(Page):
        title = "boom"
        root_component = Root
        stores = ["boom_probe"]

    app = Basis()
    app.get_session = get_session
    app.bootstrap()

    from basis.server.responses import PageResponse

    @app.get("/boom")
    async def boom(request: Request):
        return await PageResponse.from_page(BoomPage, request, render_mode="ssr")

    resp = TestClient(app).get("/boom")
    assert resp.status_code == 200
