"""Phase 2 — ``$auth``, seeded before anything renders.

The gate: ``#basis-initial-state`` carries the user projection for a logged-in
request and ``null`` for an anonymous one, on **both** SSR and CSR pages — so the
first paint is the real answer, with no login flash and no fetch-on-mount
waterfall.

The reason this is a store hook and not a component fetch is ``apply_request``:
the framework runs it on every request path *before* anything reads store state,
so the serialized initial state and the rendered tree cannot disagree.
"""

import json
import re
from datetime import timedelta

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from basis.plugins.auth import sessions
from basis.plugins.auth.models import AuthSession
from basis.plugins.auth.models_bare import User  # noqa: F401  (maps auth_user)
from basis.plugins.auth.plugin import AuthPlugin
from basis.plugins.auth.store import AuthStore
from basis.server.app import Basis
from basis.server.responses import PageResponse
from basis.shared.component import Component
from basis.shared.page import Page
from basis.shared.store import Store

PASSWORD = "correct horse battery staple"
EMAIL = "ada@example.test"
COOKIE = "basis_session"


class Root(Component):
    template = "<div><span>{$auth.authenticated}</span></div>"


class AuthPage(Page):
    title = "auth"
    root_component = Root


@pytest.fixture(autouse=True)
def _clean_registries():
    """Store blueprints outlive a request, so each test starts from none."""
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield
    Store._registry.clear()
    Store._store_blueprints.clear()


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _app(engine, page=AuthPage, **settings):
    def get_session():
        with Session(engine) as session:
            yield session

    app = Basis()
    app.get_session = get_session
    plugin = AuthPlugin(prefix="/auth", name="auth")
    plugin.configure(allow_registration=True, **settings)
    app.include_plugin(plugin)

    def _page_route(mode):
        async def handler(request: Request):
            return await PageResponse.from_page(page, request, render_mode=mode)

        return handler

    for mode in ("ssr", "csr"):
        app.add_route(
            f"/page-{mode}", _page_route(mode), methods=["GET"], name=f"page_{mode}"
        )

    return app, plugin


def _state(html):
    match = re.search(
        r'<script id="basis-initial-state"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    assert match, "basis-initial-state script not found"
    return json.loads(match.group(1))


def _auth(state):
    """The ``$auth`` slice of the serialized state."""
    assert "auth" in state, "the $auth store was not serialized"
    return state["auth"]


def _sign_in(client):
    response = client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
    assert response.status_code == 201, response.text


# ── both engines, both states ─────────────────────────────────────────────


@pytest.mark.parametrize("mode", ["ssr", "csr"])
def test_an_anonymous_request_serializes_an_anonymous_store(engine, mode):
    app, _ = _app(engine)
    with TestClient(app) as client:
        auth = _auth(_state(client.get(f"/page-{mode}").text))

        assert auth["user"] is None
        assert auth["authenticated"] is False


@pytest.mark.parametrize("mode", ["ssr", "csr"])
def test_a_logged_in_request_serializes_the_user_projection(engine, mode):
    app, _ = _app(engine)
    with TestClient(app) as client:
        _sign_in(client)

        auth = _auth(_state(client.get(f"/page-{mode}").text))

        assert auth["authenticated"] is True
        assert auth["user"]["email"] == EMAIL
        assert "password_hash" not in auth["user"]


def test_both_engines_agree(engine):
    """A store whose request-time projection depended on the render mode is the
    bug the shared pipeline exists to prevent."""
    app, _ = _app(engine)
    with TestClient(app) as client:
        _sign_in(client)

        ssr = _auth(_state(client.get("/page-ssr").text))
        csr = _auth(_state(client.get("/page-csr").text))

        assert ssr == csr


def test_the_store_projection_matches_the_session_endpoint(engine):
    """One description of an account, whether it arrives hydrated or fetched."""
    app, _ = _app(engine)
    with TestClient(app) as client:
        _sign_in(client)

        fetched = client.get("/auth/session").json()["user"]
        hydrated = _auth(_state(client.get("/page-ssr").text))["user"]

        assert hydrated == fetched


# ── what the store reports as the account changes ─────────────────────────


def test_a_revoked_session_renders_anonymous(engine):
    app, _ = _app(engine)
    with TestClient(app) as client:
        _sign_in(client)
        assert _auth(_state(client.get("/page-ssr").text))["authenticated"] is True

        client.post("/auth/logout")

        assert _auth(_state(client.get("/page-ssr").text))["user"] is None


def test_an_expired_session_renders_anonymous(engine):
    app, _ = _app(engine)
    with TestClient(app) as client:
        _sign_in(client)

        with Session(engine) as db:
            row = db.exec(select(AuthSession)).one()
            row.expires_at = row.created_at - timedelta(days=1)
            db.add(row)
            db.commit()

        assert _auth(_state(client.get("/page-ssr").text))["user"] is None


def test_an_inactive_account_renders_anonymous(engine):
    app, plugin = _app(engine)
    with TestClient(app) as client:
        _sign_in(client)

        with Session(engine) as db:
            user = db.exec(select(plugin.user_model)).one()
            user.is_active = False
            db.add(user)
            db.commit()

        assert _auth(_state(client.get("/page-ssr").text))["user"] is None


# ── the paths that must not break a page ──────────────────────────────────


def test_an_app_with_no_database_still_renders():
    """Pages must render without auth. The store reads the request's session and
    reports anonymous when there is none, rather than raising into the render —
    which is why a database-less app can ship auth and still serve its pages.
    """
    app = Basis()
    plugin = AuthPlugin(prefix="/auth", name="auth")
    app.include_plugin(plugin)

    def _page_route(mode):
        async def handler(request: Request):
            return await PageResponse.from_page(AuthPage, request, render_mode=mode)

        return handler

    app.add_route("/page", _page_route("ssr"), methods=["GET"], name="page")

    with TestClient(app) as client:
        response = client.get("/page")

        assert response.status_code == 200
        assert _auth(_state(response.text))["user"] is None


# ── wiring ────────────────────────────────────────────────────────────────


def test_the_app_exposes_the_store_and_disabling_unwinds_it(engine):
    import asyncio

    app, _ = _app(engine)

    with TestClient(app) as client:
        assert app.auth is Store._registry["auth"]
        assert "auth" in _global_store_names(app)

        assert asyncio.run(app.disable_plugin("auth")) is True

        assert "auth" not in _global_store_names(app)


def _global_store_names(app):
    return [cfg.get("name") for cfg in app._global_stores]


def test_an_app_declared_store_wins(engine):
    """The escape hatch, and the way ``$auth`` reaches the *client* without the
    plugin's components: an app's ``stores/`` module-scope instance is declared
    before ``bootstrap`` discovers plugins, so ``include_store`` adopts it — the
    same contract ``$theme`` has (D5-era blueprint reuse)."""
    class AppAuth(AuthStore):
        def __init__(self, name="auth"):
            super().__init__(name)
            self.site = "example"

    mine = AppAuth("auth")  # the app's stores/ module-scope instance

    app, _ = _app(engine)

    with TestClient(app) as client:
        assert app.auth is mine
        assert Store._registry["auth"] is mine

        _sign_in(client)
        auth = _auth(_state(client.get("/page-ssr").text))

        assert auth["user"]["email"] == EMAIL
        assert auth["site"] == "example", "the app's own field flows through"


def test_a_strict_page_subset_must_name_auth(engine):
    """D8: ``$auth`` is plugin-registered, so a page that declares its own store
    subset opts out of it unless it says otherwise (exactly like ``$regions``)."""
    class Subset(Page):
        title = "subset"
        root_component = Root
        stores = ["plugins"]

    app, _ = _app(engine, page=Subset)
    with TestClient(app) as client:
        state = _state(client.get("/page-ssr").text)

        assert "auth" not in state


def test_a_strict_page_subset_that_names_auth_gets_it(engine):
    class Subset(Page):
        title = "subset"
        root_component = Root
        stores = ["plugins", "auth"]

    app, _ = _app(engine, page=Subset)
    with TestClient(app) as client:
        _sign_in(client)

        assert _auth(_state(client.get("/page-ssr").text))["user"]["email"] == EMAIL


def test_a_component_can_bind_auth_state(engine):
    """The rendered tree reads the same value the initial state ships. For a
    logged-in request the text node carries the real value — an *empty* one
    hydrates as an unmatched binding, which is why auth components must not
    render the anonymous case as text (§6)."""
    app, _ = _app(engine)
    with TestClient(app) as client:
        _sign_in(client)
        html = client.get("/page-ssr").text

        assert ">True<" in html, "the bound value was rendered, not an empty node"
