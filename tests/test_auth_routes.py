"""Phase 1c — the ``/auth`` HTTP surface and the session lifecycle.

The gate: register → login sets an ``HttpOnly`` cookie → ``GET /auth/session``
returns the user → logout clears it → ``GET /auth/session`` returns ``null``;
login rotates (the previous row is gone); ``logout-all`` ends every session for
the user.

A fresh plugin instance per test rather than the module singleton, so settings
cannot leak between them.
"""

from contextlib import contextmanager
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from basis.plugins.auth import routes, throttle
from basis.plugins.auth.models import AuthSession, LoginAttempt, utcnow
from basis.plugins.auth.plugin import AuthConfigError, AuthPlugin
from basis.server.app import Basis

# Imported for its mapping, not its class: ``auth_session.user_id`` carries a
# foreign key to ``auth_user``, so the tables must be mapped together before the
# engine fixture runs ``create_all``. The plugin cannot be in the other state —
# ``on_register`` always resolves a user model — so the default variant stands in.
from basis.plugins.auth.models_bare import User  # noqa: F401

PASSWORD = "correct horse battery staple"
EMAIL = "ada@example.com"


def _engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _app(engine, **settings):
    """A booted app serving ``/auth``, with the plugin configured as asked."""
    def get_session():
        with Session(engine) as session:
            yield session

    app = Basis()
    app.get_session = get_session
    plugin = AuthPlugin(prefix="/auth", name="auth")
    plugin.configure(**settings)
    app.include_plugin(plugin)
    return app, plugin


@contextmanager
def _client(engine, **settings):
    app, plugin = _app(engine, **settings)
    with TestClient(app) as client:
        yield client, plugin


@pytest.fixture
def engine():
    return _engine()


def _register(client, email=EMAIL, password=PASSWORD, **extra):
    return client.post("/auth/register", json={"email": email, "password": password, **extra})


def _login(client, email=EMAIL, password=PASSWORD):
    return client.post("/auth/login", json={"email": email, "password": password})


def _sessions(engine):
    with Session(engine) as session:
        return session.exec(select(AuthSession)).all()


# ── the gate: register → login → session → logout ─────────────────────────


def test_register_login_session_logout_round_trip(engine):
    with _client(engine, allow_registration=True) as (client, plugin):
        assert client.get("/auth/session").json() == {"user": None}

        created = _register(client, display_name="Ada")
        assert created.status_code == 201
        assert created.json()["user"]["email"] == EMAIL
        assert created.json()["user"]["display_name"] == "Ada"

        # Registering signs the new account in, so the caller is not left
        # staring at a login form they just filled in.
        assert client.get("/auth/session").json()["user"]["email"] == EMAIL

        assert client.post("/auth/logout").status_code == 204
        assert client.get("/auth/session").json() == {"user": None}

        logged_in = _login(client)
        assert logged_in.status_code == 200
        assert logged_in.json()["user"]["email"] == EMAIL
        assert client.get("/auth/session").json()["user"]["email"] == EMAIL


def test_session_cookie_is_httponly_and_lax(engine):
    with _client(engine, allow_registration=True) as (client, _):
        cookie = _register(client).headers["set-cookie"]

        assert cookie.startswith("basis_session=")
        assert "HttpOnly" in cookie
        assert "SameSite=lax" in cookie
        assert "Path=/" in cookie
        assert "Max-Age=" in cookie
        assert "Secure" not in cookie, "a plain-HTTP app must not claim the Secure flag"


def test_cookie_name_is_configurable(engine):
    with _client(engine, allow_registration=True, cookie_name="sid") as (client, _):
        assert _register(client).headers["set-cookie"].startswith("sid=")


def test_trust_proxy_makes_forwarded_scheme_authoritative(engine):
    with _client(engine, allow_registration=True, trust_proxy=True) as (client, _):
        response = client.post(
            "/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert "Secure" in response.headers["set-cookie"]


def test_forwarded_scheme_is_ignored_without_trust_proxy(engine):
    """A direct caller must not be able to talk the app into a cookie the
    browser then refuses to send back over HTTP."""
    with _client(engine, allow_registration=True) as (client, _):
        response = client.post(
            "/auth/register",
            json={"email": EMAIL, "password": PASSWORD},
            headers={"X-Forwarded-Proto": "https"},
        )
        assert "Secure" not in response.headers["set-cookie"]


def test_login_rotates_the_session(engine):
    """Session fixation: the session the caller arrived with is not the one they
    leave with."""
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)
        before = [row.token_hash for row in _sessions(engine)]

        _login(client)
        after = [row.token_hash for row in _sessions(engine)]

        assert len(after) == 1
        assert before[0] not in after


def test_logout_clears_the_cookie(engine):
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)
        response = client.post("/auth/logout")

        assert response.status_code == 204
        cleared = response.headers["set-cookie"]
        assert "Max-Age=0" in cleared
        assert _sessions(engine) == []


def test_logout_all_ends_every_session(engine):
    """Two devices, one account: logging out everywhere ends both."""
    app, _ = _app(engine, allow_registration=True)
    with TestClient(app) as device_a, TestClient(app) as device_b:
        assert _register(device_a).status_code == 201
        assert _login(device_b).status_code == 200
        assert len(_sessions(engine)) == 2

        revoked = device_a.post("/auth/logout-all")
        assert revoked.status_code == 200
        assert revoked.json() == {"revoked": 2}

        assert _sessions(engine) == []
        assert device_b.get("/auth/session").json() == {"user": None}


# ── failures are uniform and indistinguishable ────────────────────────────


def test_unknown_email_and_wrong_password_are_indistinguishable(engine):
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)

        wrong = _login(client, password="not the password")
        missing = _login(client, email="nobody@example.com")

        assert wrong.status_code == missing.status_code == 401
        assert wrong.json() == missing.json()


def test_unknown_email_still_pays_one_kdf(engine, monkeypatch):
    """Uniform *work*, not just uniform words: short-circuiting an unknown email
    would answer "does this account exist?" in the response time."""
    seen = []
    real = routes.verify_password

    def counting(password, encoded):
        seen.append(encoded)
        return real(password, encoded)

    monkeypatch.setattr(routes, "verify_password", counting)

    with _client(engine, allow_registration=True) as (client, _):
        _login(client, email="nobody@example.com")

        assert len(seen) == 1
        assert seen == [""], "an unknown email verifies against a dummy hash"


def test_deactivated_account_cannot_log_in_or_keep_a_session(engine):
    with _client(engine, allow_registration=True) as (client, plugin):
        _register(client)

        with Session(engine) as db:
            user = db.exec(select(plugin.user_model)).one()
            user.is_active = False
            db.add(user)
            db.commit()

        assert _login(client).status_code == 401
        assert client.get("/auth/session").json() == {"user": None}


def test_logout_without_a_session_is_401(engine):
    with _client(engine) as (client, _):
        assert client.post("/auth/logout").status_code == 401
        assert client.post("/auth/logout-all").status_code == 401


# ── the sliding window ────────────────────────────────────────────────────


def _age_session(engine, **values):
    """Rewrite the stored session, to move time without a clock shim."""
    with Session(engine) as db:
        row = db.exec(select(AuthSession)).one()
        for key, value in values.items():
            setattr(row, key, value)
        db.add(row)
        db.commit()


def test_expired_session_is_anonymous(engine):
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)
        _age_session(engine, expires_at=datetime(2000, 1, 1))

        assert client.get("/auth/session").json() == {"user": None}

        # An expired cookie is not a lockout: the credentials still work, and
        # logging in replaces the dead session.
        assert _login(client).status_code == 200
        assert client.get("/auth/session").json()["user"]["email"] == EMAIL


def test_session_in_use_is_extended(engine):
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)
        _age_session(engine, expires_at=datetime(2999, 1, 1), last_seen_at=datetime(2000, 1, 1))

        assert client.get("/auth/session").json()["user"]["email"] == EMAIL

        with Session(engine) as db:
            row = db.exec(select(AuthSession)).one()

        assert row.expires_at < datetime(2999, 1, 1), "the window moved forward"
        assert row.last_seen_at > datetime(2000, 1, 1)


def test_unknown_cookie_value_is_anonymous(engine):
    with _client(engine, allow_registration=True) as (client, _):
        client.cookies.set("basis_session", "not-a-real-token")

        assert client.get("/auth/session").json() == {"user": None}


def test_malformed_bodies_are_422(engine):
    with _client(engine, allow_registration=True) as (client, _):
        assert client.post("/auth/login", content=b"not json").status_code == 422
        assert client.post("/auth/login", json={"email": EMAIL}).status_code == 422
        assert client.post("/auth/login", json=["a"]).status_code == 422


# ── registration policy ───────────────────────────────────────────────────


def test_registration_is_off_by_default(engine):
    """Fail-closed (D15): the CLI bootstraps the first account."""
    with _client(engine) as (client, _):
        assert _register(client).status_code == 403


def test_weak_password_is_rejected(engine):
    with _client(engine, allow_registration=True) as (client, _):
        response = _register(client, password="short")

        assert response.status_code == 422
        assert "8" in response.json()["detail"], "the message names the minimum"


def test_password_policy_is_overridable(engine):
    with _client(engine, allow_registration=True, password_min_length=20) as (client, _):
        assert _register(client, password="sixteen-chars-ok").status_code == 422
        assert _register(client, email="b@c.d", password="twenty-plus-chars-ok!").status_code == 201


def test_password_check_hook_can_reject(engine):
    def no_emails(password):
        return "Passwords cannot contain '@'" if "@" in password else None

    with _client(
        engine, allow_registration=True, password_check=no_emails
    ) as (client, _):
        rejected = _register(client, password="ada@example.com")
        assert rejected.status_code == 422
        assert rejected.json()["detail"] == "Passwords cannot contain '@'"

        assert _register(client, email="b@c.d", password=PASSWORD).status_code == 201


def test_taken_email_is_409(engine):
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)

        assert _register(client).status_code == 409


def test_registration_does_not_return_the_password_hash(engine):
    with _client(engine, allow_registration=True) as (client, _):
        user = _register(client).json()["user"]

        assert "password_hash" not in user
        assert set(user) == {
            "id",
            "email",
            "display_name",
            "is_active",
            "is_superuser",
            "roles",
            "created_at",
        }


# ── the deferred session-getter check ─────────────────────────────────────


def test_missing_session_getter_fails_on_first_use_not_at_boot():
    """Auth is installed in apps with no database at all, so ``on_register``
    cannot demand a session getter — the failure belongs on the app that uses
    auth, naming the fix."""
    app = Basis()
    plugin = AuthPlugin(prefix="/auth", name="auth")
    app.include_plugin(plugin)  # must not raise

    with TestClient(app) as client:
        with pytest.raises(AuthConfigError, match="app.get_session"):
            client.get("/auth/session")


# ── lockout (D13) ─────────────────────────────────────────────────────────


def _fail(client, times, email=EMAIL):
    for _ in range(times):
        response = _login(client, email=email, password="wrong")
    return response


def test_reaching_the_threshold_locks_the_next_attempt(engine):
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)

        assert _fail(client, 5).status_code == 401, "the locking failure is still a 401"

        locked = _login(client, password="wrong")
        assert locked.status_code == 429
        assert int(locked.headers["retry-after"]) > 0


def test_lockout_holds_even_for_the_correct_password(engine):
    """Otherwise a lockout would only be a speed bump for an attacker who
    already has the password."""
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)
        _fail(client, 5)

        assert _login(client).status_code == 429


def test_a_correct_login_clears_the_counter(engine):
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)
        _fail(client, 4)
        assert _login(client).status_code == 200

        # Four more failures must still not lock: had the counter survived the
        # success, the second of these would already be a 429.
        for _ in range(4):
            assert _login(client, password="wrong").status_code == 401


def test_lockout_is_a_row_not_memory(engine):
    """D13 — the point of storing it: a restart does not hand an attacker a
    fresh allowance."""
    first, _ = _app(engine, allow_registration=True)
    with TestClient(first) as client:
        _register(client)
        _fail(client, 5)
        assert _login(client, password="wrong").status_code == 429

    # A restart: a new app and a new plugin instance, sharing only the database.
    second, _ = _app(engine, allow_registration=True)
    with TestClient(second) as client:
        assert _login(client, password="wrong").status_code == 429


def test_an_unknown_email_is_counted_too(engine):
    """A throttle that only counted real accounts would answer "does this
    account exist?" by never locking."""
    with _client(engine, allow_registration=True) as (client, _):
        assert _fail(client, 5, email="nobody@example.com").status_code == 401

        assert _login(client, email="nobody@example.com", password="wrong").status_code == 429


def test_lockout_is_per_account_not_per_caller(engine):
    """One locked key must not lock the same caller out of another account."""
    with _client(engine, allow_registration=True) as (client, _):
        _register(client)
        _fail(client, 5)
        assert _login(client, password="wrong").status_code == 429

        other = _login(client, email="grace@example.com", password="wrong")
        assert other.status_code == 401, "a different account has its own key"


def test_lockout_is_configurable(engine):
    with _client(
        engine, allow_registration=True, lockout_threshold=2, lockout_duration=60
    ) as (client, _):
        _register(client)
        _fail(client, 2)

        locked = _login(client, password="wrong")
        assert locked.status_code == 429
        assert 0 < int(locked.headers["retry-after"]) <= 60


def test_login_works_again_once_the_lock_expires(engine):
    """A lockout must be temporary, never a bricked account."""
    with _client(engine, allow_registration=True, lockout_threshold=1) as (client, _):
        _register(client)
        assert _login(client, password="wrong").status_code == 401
        assert _login(client).status_code == 429

        _age_attempt(engine, locked_until=utcnow() - timedelta(seconds=1))

        assert _login(client).status_code == 200


def _age_attempt(engine, **values):
    """Rewrite the stored attempt row, to move time without a clock shim."""
    with Session(engine) as db:
        row = db.exec(select(LoginAttempt)).one()
        for key, value in values.items():
            setattr(row, key, value)
        db.add(row)
        db.commit()


# ── the throttle itself ───────────────────────────────────────────────────


def test_key_pairs_the_caller_with_the_account():
    assert throttle.key_for("1.2.3.4", "ada@example.com") == "1.2.3.4|ada@example.com"
    assert throttle.key_for(None, "ada@example.com") == "unknown|ada@example.com"


def test_failures_outside_the_window_are_forgotten(engine):
    """Only a burst locks; a slow trickle of typos never accumulates."""
    key = throttle.key_for("1.2.3.4", EMAIL)
    with Session(engine) as db:
        for _ in range(4):
            throttle.record_failure(db, key, threshold=5, window=300, duration=900)
        assert throttle.check_locked(db, key) is None

        row = db.get(LoginAttempt, key)
        row.window_start = utcnow() - timedelta(seconds=301)
        db.add(row)
        db.commit()

        throttle.record_failure(db, key, threshold=5, window=300, duration=900)
        db.refresh(row)

        assert row.count == 1, "the window rolled, so the count restarted"


def test_an_expired_lock_is_not_a_lock(engine):
    key = throttle.key_for("1.2.3.4", EMAIL)
    with Session(engine) as db:
        for _ in range(5):
            throttle.record_failure(db, key, threshold=5, window=300, duration=900)
        assert throttle.check_locked(db, key) is not None

        row = db.get(LoginAttempt, key)
        row.locked_until = utcnow() - timedelta(seconds=1)
        db.add(row)
        db.commit()

        assert throttle.check_locked(db, key) is None


def test_clearing_removes_the_row(engine):
    key = throttle.key_for("1.2.3.4", EMAIL)
    with Session(engine) as db:
        throttle.record_failure(db, key, threshold=5, window=300, duration=900)
        throttle.clear_failures(db, key)

        assert db.get(LoginAttempt, key) is None
        assert throttle.check_locked(db, key) is None

        # Clearing a key that has no row is a no-op, not an error.
        throttle.clear_failures(db, key)
