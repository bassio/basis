"""Phase 1e — password reset and the mailer seam.

The gate: ``request`` answers identically for a known and an unknown address;
``reset`` consumes a single-use token, sets the new password and revokes existing
sessions; with no mailer (or secret, or public origin) configured the routes
answer 501 rather than quietly doing nothing (D16).

The reset token is signed and stateless — bound to the password hash it was
minted against, so using it, or changing the password any other way, retires it.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from basis.plugins.auth import tokens
from basis.plugins.auth.models import AuthSession
from basis.plugins.auth.plugin import AuthPlugin
from basis.server.app import Basis

# Imported for its mapping, not its class: ``auth_session.user_id`` carries a
# foreign key to ``auth_user``, so the tables must be mapped together before the
# engine fixture runs ``create_all``.
from basis.plugins.auth.models_bare import User  # noqa: F401

PASSWORD = "correct horse battery staple"
NEW_PASSWORD = "a brand new battery staple"
EMAIL = "ada@example.test"
SECRET = "test-secret"
PUBLIC_URL = "https://example.test"


class Mailbox:
    """The app-supplied mailer, recording what it was asked to deliver."""

    def __init__(self):
        self.sent = []

    def __call__(self, to, subject, body):
        self.sent.append((to, subject, body))

    @property
    def token(self):
        """The reset token out of the most recent message's link."""
        body = self.sent[-1][2]
        return body.split("?token=")[1].split("\n")[0].strip()


@pytest.fixture
def engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def mailbox():
    return Mailbox()


def _app(engine, mailbox, **settings):
    def get_session():
        with Session(engine) as session:
            yield session

    app = Basis()
    app.get_session = get_session
    plugin = AuthPlugin(prefix="/auth", name="auth")
    plugin.configure(
        **{
            "mailer": mailbox,
            "secret_key": SECRET,
            "public_url": PUBLIC_URL,
            "allow_registration": True,
            **settings,
        }
    )
    app.include_plugin(plugin)
    return app, plugin


@pytest.fixture
def client(engine, mailbox):
    app, _ = _app(engine, mailbox)
    with TestClient(app) as client:
        yield client


def _register(client, email=EMAIL, password=PASSWORD):
    return client.post("/auth/register", json={"email": email, "password": password})


def _request_reset(client, email=EMAIL):
    return client.post("/auth/password/request", json={"email": email})


def _reset(client, token, password=NEW_PASSWORD):
    return client.post("/auth/password/reset", json={"token": token, "password": password})


def _login(client, email=EMAIL, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def _sessions(engine):
    with Session(engine) as session:
        return session.exec(select(AuthSession)).all()


# ── the request endpoint says nothing ─────────────────────────────────────


def test_a_known_and_an_unknown_address_are_answered_identically(engine, mailbox):
    app, _ = _app(engine, mailbox)
    with TestClient(app) as client:
        _register(client)

        known = _request_reset(client)
        unknown = _request_reset(client, email="nobody@example.test")

        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        assert len(mailbox.sent) == 1, "only the address that exists gets mail"


def test_a_deactivated_account_gets_no_mail(engine, mailbox):
    app, plugin = _app(engine, mailbox)
    with TestClient(app) as client:
        _register(client)
        with Session(engine) as db:
            user = db.exec(select(plugin.user_model)).one()
            user.is_active = False
            db.add(user)
            db.commit()

        assert _request_reset(client).status_code == 200
        assert mailbox.sent == []


def test_a_failing_mailer_does_not_leak_that_the_account_exists(engine):
    """A 500 from here would fire only for addresses that exist — the mail
    server handing over an account-existence oracle."""
    def broken(to, subject, body):
        raise RuntimeError("smtp is down")

    app, _ = _app(engine, broken)
    with TestClient(app) as client:
        _register(client)

        known = _request_reset(client)
        unknown = _request_reset(client, email="nobody@example.test")

        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()


# ── the reset endpoint works ──────────────────────────────────────────────


def test_the_mailed_link_carries_a_usable_token(client, mailbox):
    _register(client)
    _request_reset(client)

    to, subject, body = mailbox.sent[-1]

    assert to == EMAIL
    assert "password" in subject.lower()
    assert f"{PUBLIC_URL}/reset-password?token={mailbox.token}" in body
    assert _reset(client, mailbox.token).status_code == 200


def test_reset_sets_the_new_password(client, mailbox):
    _register(client)
    _request_reset(client)

    assert _reset(client, mailbox.token).status_code == 200
    client.post("/auth/logout")

    assert _login(client, password=PASSWORD).status_code == 401
    assert _login(client, password=NEW_PASSWORD).status_code == 200


def test_reset_revokes_every_existing_session(engine, mailbox):
    app, _ = _app(engine, mailbox)
    with TestClient(app) as device_a, TestClient(app) as device_b:
        _register(device_a)
        assert _login(device_b).status_code == 200
        assert len(_sessions(engine)) == 2

        _request_reset(device_a)
        assert _reset(device_a, mailbox.token).status_code == 200

        assert _sessions(engine) == []
        assert device_b.get("/auth/session").json() == {"user": None}


# ── the token is single-use ───────────────────────────────────────────────


def test_the_token_cannot_be_used_twice(client, mailbox):
    _register(client)
    _request_reset(client)
    token = mailbox.token

    assert _reset(client, token).status_code == 200
    assert _reset(client, token).status_code == 400


def test_changing_the_password_retires_any_other_outstanding_token(client, mailbox):
    """The stamp binds a token to the password it was minted against, so the
    links are not independent — the first one dies with the second."""
    _register(client)
    _request_reset(client)
    first = mailbox.token
    _request_reset(client)
    second = mailbox.token

    assert _reset(client, second).status_code == 200
    assert _reset(client, first).status_code == 400


def test_a_weak_password_does_not_burn_the_token(client, mailbox):
    _register(client)
    _request_reset(client)
    token = mailbox.token

    assert _reset(client, token, password="short").status_code == 422
    assert _reset(client, token).status_code == 200, "the link is still good"


def test_an_expired_token_is_refused(engine, mailbox):
    app, _ = _app(engine, mailbox, reset_token_ttl=-1)
    with TestClient(app) as client:
        _register(client)
        _request_reset(client)

        assert _reset(client, mailbox.token).status_code == 400


def test_a_token_signed_with_another_secret_is_refused(client):
    forged = tokens.mint_reset_token(1, "whatever", secret="not-the-secret", ttl=600)

    assert _reset(client, forged).status_code == 400


def test_a_token_for_a_missing_account_is_refused(client):
    forged = tokens.mint_reset_token(99999, "whatever", secret=SECRET, ttl=600)

    assert _reset(client, forged).status_code == 400


def test_malformed_tokens_are_refused(client):
    for token in ("", "nonsense", "a.b.c", "é", ".", "AAAA."):
        assert _reset(client, token).status_code in (400, 422), token


# ── reset is 501 until it is configured (D16) ─────────────────────────────


@pytest.mark.parametrize(
    "missing", ["mailer", "secret_key", "public_url"]
)
def test_reset_is_501_when_a_piece_is_missing(engine, mailbox, missing):
    app, _ = _app(engine, mailbox, **{missing: None})
    with TestClient(app) as client:
        for response in (_request_reset(client), _reset(client, "whatever")):
            assert response.status_code == 501
            assert missing in response.json()["detail"], "the message names the fix"
