"""Phase 1 exit criterion — the plugin unwinds and comes back.

Auth has to be an ordinary plugin: `disable_plugin` must take its routes and
models away, and `enable_plugin` must put them back. Anything it registers by
hand, outside the framework's revertible lifecycle, shows up here as a route that
survives its own plugin.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from basis.plugins.auth.models import AuthSession, LoginAttempt
from basis.plugins.auth.plugin import AuthPlugin
from basis.server.app import Basis

from basis.plugins.auth.models_bare import User  # noqa: F401  (maps auth_user)

PASSWORD = "correct horse battery staple"
EMAIL = "ada@example.test"


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _app(engine):
    def get_session():
        with Session(engine) as session:
            yield session

    app = Basis()
    app.get_session = get_session
    plugin = AuthPlugin(prefix="/auth", name="auth")
    app.include_plugin(plugin)
    return app, plugin


def _auth_paths(app):
    return {route.path for route in app.routes if route.path.startswith("/auth")}


def test_disabling_the_plugin_takes_its_routes_and_models_away(engine):
    app, plugin = _app(engine)

    with TestClient(app) as client:  # entering bootstraps the app
        client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})
        assert _auth_paths(app), "the surface is registered"

        assert asyncio.run(app.disable_plugin("auth")) is True

        assert _auth_paths(app) == set()
        assert client.get("/auth/session").status_code == 404
        assert not {AuthSession, LoginAttempt, User} & app.models


def test_enabling_the_plugin_puts_it_back(engine):
    app, plugin = _app(engine)

    with TestClient(app) as client:
        before = _auth_paths(app)

        assert asyncio.run(app.disable_plugin("auth")) is True
        assert asyncio.run(app.enable_plugin("auth")) is True

        assert _auth_paths(app) == before
        assert client.get("/auth/session").json() == {"user": None}
