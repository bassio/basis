"""The auth HTTP surface — everything under ``/auth``.

Declared by :func:`declare_routes`, which ``AuthPlugin.__init__`` calls while
building a plugin instance. That timing is not a style choice: the app copies a
plugin's router into its own route table once, at ``include_plugin`` time, so a
route added afterwards is never served. The endpoints therefore have to exist on
the router *before* the plugin is registered — which also rules out decorating
them at this module's top level, since there is no ``plugin`` here to decorate
with.

Two consequences of the package being served to the browser at
``/basis/plugins/auth`` follow from that:

- nothing client-hostile is imported at module scope. Every server-only import
  happens inside a function body, so importing this module in PyScript is
  harmless — the shim's route decorators are no-ops and no handler ever runs;
- request bodies are parsed from JSON by hand rather than with pydantic models,
  because a model declared here would have to exist *in the browser* for the
  decorator to see it. These bodies are three fields at most, so validating them
  directly costs less than the machinery it would replace.

Handlers are async so they can read the body, and the password KDF — the one
genuinely heavy, memory-hard operation on this surface — is pushed to the
threadpool, where OpenSSL releases the GIL. Database access stays synchronous,
matching the framework's DB/store posture (D12).
"""

from contextlib import asynccontextmanager
from datetime import timedelta
import logging

from basis.shared.plugin import Request

from basis.plugins.auth.crypto import hash_password, needs_rehash, verify_password

from basis.plugins.auth.tokens import (
    mint_reset_token,
    password_stamp,
    read_reset_token,
)

_log = logging.getLogger("basis.plugins.auth")


def declare_routes(plugin) -> None:
    """Declare the auth endpoints on *plugin*'s router.

    Takes the plugin rather than reading a module global, so every instance owns
    its own routes and nothing is shared through module state.
    """

    @plugin.get("/session")
    async def get_session(request: Request):
        """Who the caller is — ``null`` when nobody is logged in.

        The no-SSR fallback path (§6): a page rendered without a server-side
        answer to "who is this?" asks here once it is mounted.
        """
        async with _db(request) as db:
            sessions = _sessions()
            row = _session_row(plugin, request, db)
            user = _user_for(plugin, db, row)
            if user is not None:
                # Refresh the sliding window. Resolution itself never writes —
                # ``$auth`` seeds through it on every render.
                sessions.touch_session(db, row, ttl=_ttl(plugin))
            return _json({"user": _projection(user) if user is not None else None})

    @plugin.post("/login")
    async def login(request: Request):
        from starlette.concurrency import run_in_threadpool

        payload = await _json_body(request)
        email, password = _credentials(payload)
        if email is None or password is None:
            return _json({"detail": "email and password are required"}, 422)

        async with _db(request) as db:
            sessions = _sessions()
            throttle = _throttle()
            key = throttle.key_for(_client_ip(request), email)

            user = _find_user(plugin, db, email)
            # Uniform work, not just uniform words: an unknown email still pays
            # one KDF, so response time cannot answer "does this account exist?".
            encoded = user.password_hash if user is not None else ""
            verified = await run_in_threadpool(verify_password, password, encoded)

            # Read *after* the verification, never before it: a lockout must not
            # become the cheap response that answers "is this key locked?"
            # ahead of the work every other failure pays for.
            locked_until = throttle.check_locked(db, key)
            if locked_until is not None:
                return _locked(locked_until)

            if user is None or not verified or not user.is_active:
                throttle.record_failure(db, key, **_lockout(plugin))
                return _json({"detail": "Invalid credentials"}, 401)

            # Proving the password resets the window, so occasional typos never
            # accumulate into a lockout.
            throttle.clear_failures(db, key)

            # Upgrade-on-login: an outdated hash is replaced now, while the
            # plaintext is in hand and known to be correct.
            if needs_rehash(encoded):
                user.password_hash = await run_in_threadpool(hash_password, password)
                db.add(user)

            # Session fixation: whatever session the caller arrived with is not
            # the one they leave with.
            sessions.revoke_session(db, _cookie(request, plugin))
            token = sessions.create_session(
                db,
                user,
                ttl=_ttl(plugin),
                user_agent=_user_agent(request),
                ip=_client_ip(request),
            )
            response = _json({"user": _projection(user)})
            _set_cookie(plugin, request, response, token)
            return response

    @plugin.post("/logout")
    async def logout(request: Request):
        async with _db(request) as db:
            sessions = _sessions()
            if not sessions.revoke_session(db, _cookie(request, plugin)):
                return _json({"detail": "Not authenticated"}, 401)
            response = _empty()
            _clear_cookie(plugin, request, response)
            return response

    @plugin.post("/logout-all")
    async def logout_all(request: Request):
        """End every session for the caller — the "I lost my laptop" button."""
        async with _db(request) as db:
            sessions = _sessions()
            row = _session_row(plugin, request, db)
            user = _user_for(plugin, db, row)
            if user is None:
                return _json({"detail": "Not authenticated"}, 401)
            revoked = sessions.revoke_all_sessions(db, user.id)
            response = _json({"revoked": revoked})
            _clear_cookie(plugin, request, response)
            return response

    @plugin.post("/register")
    async def register(request: Request):
        from starlette.concurrency import run_in_threadpool

        if not plugin._config()["allow_registration"]:
            return _json({"detail": "Registration is disabled"}, 403)

        payload = await _json_body(request)
        email, password = _credentials(payload)
        if email is None or password is None:
            return _json({"detail": "email and password are required"}, 422)
        problem = _password_problem(plugin, password)
        if problem is not None:
            return _json({"detail": problem}, 422)

        async with _db(request) as db:
            sessions = _sessions()
            if _find_user(plugin, db, email) is not None:
                # The one accepted account-existence oracle: a policy of "this
                # email is taken" is inherent to registration (§Phase 1).
                return _json({"detail": "Email is already registered"}, 409)

            user = plugin.user_model(
                email=email,
                password_hash=await run_in_threadpool(hash_password, password),
                display_name=_text(payload, "display_name"),
            )
            db.add(user)
            db.commit()
            db.refresh(user)

            token = sessions.create_session(
                db,
                user,
                ttl=_ttl(plugin),
                user_agent=_user_agent(request),
                ip=_client_ip(request),
            )
            response = _json({"user": _projection(user)}, 201)
            _set_cookie(plugin, request, response, token)
            return response

    @plugin.post("/password/request")
    async def password_request(request: Request):
        """Email a reset link, if there is an account to email it to.

        The answer is the same either way — whether an address has an account
        here is not ours to tell. Sending the mail is the only asymmetry, and it
        cannot be avoided: without an account there is no address to send to.
        """
        from starlette.concurrency import run_in_threadpool

        config = plugin._config()
        blocker = _reset_blocker(config)
        if blocker is not None:
            return _json({"detail": blocker}, 501)

        payload = await _json_body(request)
        email = _text(payload or {}, "email")
        if email is None:
            return _json({"detail": "email is required"}, 422)

        pending = None
        async with _db(request) as db:
            user = _find_user(plugin, db, email)
            if user is not None and user.is_active:
                pending = (
                    user.email,
                    mint_reset_token(
                        user.id,
                        user.password_hash,
                        secret=config["secret_key"],
                        ttl=config["reset_token_ttl"],
                    ),
                )

        if pending is not None:
            to, token = pending
            minutes = max(1, int(config["reset_token_ttl"]) // 60)
            try:
                await run_in_threadpool(
                    config["mailer"],
                    to,
                    *_reset_message(_reset_link(config, token), minutes),
                )
            except Exception:
                # The operator needs to know; the caller must not. A 500 here
                # would fire only for addresses that exist — an account-existence
                # oracle handed over by a broken mail server.
                _log.exception("Password reset mail to %s failed", to)

        return _json({"ok": True})

    @plugin.post("/password/reset")
    async def password_reset(request: Request):
        """Consume a reset token: set the password, retire every session."""
        from starlette.concurrency import run_in_threadpool

        config = plugin._config()
        blocker = _reset_blocker(config)
        if blocker is not None:
            return _json({"detail": blocker}, 501)

        payload = await _json_body(request)
        token = _secret(payload or {}, "token")
        password = _secret(payload or {}, "password")
        if token is None or password is None:
            return _json({"detail": "token and password are required"}, 422)

        claim = read_reset_token(token, secret=config["secret_key"])
        if claim is None:
            return _json({"detail": _BAD_RESET}, 400)

        problem = _password_problem(plugin, password)
        if problem is not None:
            return _json({"detail": problem}, 422)

        async with _db(request) as db:
            sessions = _sessions()
            user = db.get(plugin.user_model, claim.user_id)
            # The stamp is what makes the token single-use: it was minted against
            # the password hash of that moment, so consuming it — or changing the
            # password by any other route — retires it.
            if (
                user is None
                or not user.is_active
                or claim.stamp != password_stamp(user.password_hash, secret=config["secret_key"])
            ):
                return _json({"detail": _BAD_RESET}, 400)

            user.password_hash = await run_in_threadpool(hash_password, password)
            db.add(user)
            db.commit()
            # Whoever else was signed in is not the person who just proved they
            # own the address.
            sessions.revoke_all_sessions(db, user.id)

            return _json({"ok": True})


# ── request-scoped plumbing ───────────────────────────────────────────────


@asynccontextmanager
async def _db(request: Request):
    """The request's database session, released afterwards.

    ``server.db.get_db_session`` is the framework's single description of what
    ``app.get_session`` may be — generator, async generator, context manager or
    a plain callable — so it is driven here rather than described a second time.

    The missing-getter check lives here, not in ``on_register``: auth is
    installed in every app that has the package, including apps with no database
    at all, so a boot-time demand would break apps that never wanted auth. This
    raises instead, on the app that actually uses it.
    """
    from basis.plugins.auth.plugin import AuthConfigError
    from basis.server.db import get_db_session

    if getattr(request.app, "get_session", None) is None:
        raise AuthConfigError(
            "Auth needs a database session: set `app.get_session = <getter>` "
            "before `app.bootstrap()`, or disable the auth plugin."
        )

    session_factory = get_db_session(request)
    db = await anext(session_factory)
    try:
        yield db
    finally:
        await session_factory.aclose()


def _session_row(plugin, request, db):
    return _sessions().resolve_session(db, _cookie(request, plugin))


def _sessions():
    """The session store, imported on use.

    ``sessions.py`` needs sqlmodel, and this module is imported in the browser,
    so the import cannot sit at module scope.
    """
    from basis.plugins.auth import sessions

    return sessions


def _throttle():
    """The login throttle — server-only, imported on use for the same reason."""
    from basis.plugins.auth import throttle

    return throttle


def _user_for(plugin, db, row):
    """The user behind *row*, or ``None``.

    A deactivated account is anonymous: it is not an error a caller should be
    able to distinguish from "no session", and every existing session for it
    stops working the moment the flag flips.
    """
    if row is None:
        return None
    user = db.get(plugin.user_model, row.user_id)
    if user is None or not user.is_active:
        return None
    return user


def _find_user(plugin, db, email):
    from sqlmodel import select

    return db.exec(select(plugin.user_model).where(plugin.user_model.email == email)).first()


def _projection(user):
    from basis.plugins.auth.models import user_projection

    return user_projection(user)


def _credentials(payload):
    """``(email, password)`` from a decoded body, each ``None`` when unusable."""
    if payload is None:
        return None, None
    return _text(payload, "email"), _secret(payload, "password")


def _text(payload, key):
    """A trimmed, non-empty string field — for values where whitespace is noise."""
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _secret(payload, key):
    """A non-empty string field, left exactly as sent.

    Never trimmed: leading or trailing whitespace is part of the password, and
    normalising it here would silently change what was hashed at registration.
    """
    value = payload.get(key)
    return value if isinstance(value, str) and value else None


async def _json_body(request):
    """The body as a dict, or ``None`` when it is anything else."""
    try:
        payload = await request.json()
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _password_problem(plugin, password):
    """Why *password* is unacceptable, or ``None``.

    Minimum length plus an optional app-supplied hook — no composition rules,
    which are known to push users toward predictable patterns (§Phase 1).
    """
    config = plugin._config()
    minimum = config["password_min_length"]
    if len(password) < minimum:
        return f"Password must be at least {minimum} characters"
    check = config["password_check"]
    if check is not None:
        return check(password) or None
    return None


# ── password reset ────────────────────────────────────────────────────────

#: One answer for a bad signature, an expired token, an unknown account and an
#: already-consumed one. Telling them apart would only help whoever is guessing.
_BAD_RESET = "This reset link is invalid or has expired"


def _reset_blocker(config) -> str | None:
    """What stops password reset working, or ``None``.

    Three things are required, and none has a safe default:

    - a **transport**, because the plugin ships none (D16: a silent no-op hides
      the misconfiguration from the operator);
    - a **secret**, because a per-process random one would break silently the
      moment the app runs more than one worker — the same trap D13 avoids for
      lockout state;
    - the **public origin**, because reading it from the request would let a
      spoofed ``Host`` header steer the link inside someone else's email (the
      classic reset-link poisoning attack), and behind a proxy it would be the
      internal origin anyway.
    """
    if config["mailer"] is None:
        return "Password reset is not configured: set configure(mailer=...)"
    if not config["secret_key"]:
        return "Password reset is not configured: set configure(secret_key=...)"
    if not config["public_url"]:
        return "Password reset is not configured: set configure(public_url='https://...')"
    return None


def _reset_link(config, token) -> str:
    return f"{str(config['public_url']).rstrip('/')}{config['reset_path']}?token={token}"


def _reset_message(link: str, minutes: int) -> tuple[str, str]:
    """The default mail, as ``(subject, body)``.

    Apps that want their own wording wrap their mailer and replace it — which is
    what the transport seam is for.
    """
    return (
        "Reset your password",
        "Someone asked to reset the password for this address.\n\n"
        f"Choose a new one here:\n\n{link}\n\n"
        f"The link works once, and expires in {minutes} minutes. If this wasn't "
        "you, ignore this message — the password is unchanged.",
    )


# ── cookies ───────────────────────────────────────────────────────────────


def _cookie(request, plugin):
    return request.cookies.get(plugin._config()["cookie_name"])


def _set_cookie(plugin, request, response, token) -> None:
    config = plugin._config()
    response.set_cookie(
        config["cookie_name"],
        token,
        max_age=int(_ttl(plugin).total_seconds()),
        httponly=True,
        samesite="lax",
        path="/",
        secure=_is_https(plugin, request),
    )


def _clear_cookie(plugin, request, response) -> None:
    """Delete the cookie with the same attributes it was set with (§5)."""
    response.delete_cookie(
        plugin._config()["cookie_name"],
        path="/",
        samesite="lax",
        httponly=True,
        secure=_is_https(plugin, request),
    )


def _is_https(plugin, request) -> bool:
    """Whether the *browser* is on HTTPS, which is what ``Secure`` means.

    Behind a proxy the app sees the internal scheme, so ``trust_proxy`` makes
    ``X-Forwarded-Proto`` authoritative — and it must only be switched on behind
    a proxy that sets that header itself (§5). Read here and nowhere else.
    """
    if plugin._config()["trust_proxy"]:
        forwarded = request.headers.get("x-forwarded-proto")
        if forwarded:
            return forwarded.split(",")[0].strip().lower() == "https"
    return request.url.scheme == "https"


def _ttl(plugin) -> timedelta:
    return timedelta(seconds=plugin._config()["session_ttl"])


def _user_agent(request):
    return request.headers.get("user-agent")


def _client_ip(request):
    return request.client.host if request.client else None


# ── responses ─────────────────────────────────────────────────────────────


def _lockout(plugin) -> dict:
    """The throttle's tuning, read from config in one place."""
    config = plugin._config()
    return {
        "threshold": config["lockout_threshold"],
        "window": config["lockout_window"],
        "duration": config["lockout_duration"],
    }


def _locked(locked_until):
    """429 with the wait, so the caller can say something useful (§Phase 1)."""
    from basis.plugins.auth.models import utcnow

    seconds = max(1, int((locked_until - utcnow()).total_seconds()))
    return _json(
        {"detail": "Too many failed attempts"},
        429,
        headers={"Retry-After": str(seconds)},
    )


def _json(payload, status: int = 200, headers=None):
    from fastapi.responses import JSONResponse

    return JSONResponse(payload, status_code=status, headers=headers)


def _empty():
    from fastapi.responses import Response

    return Response(status_code=204)
