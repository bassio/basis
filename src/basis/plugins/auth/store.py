"""The ``$auth`` store — who is asking, known before anything renders.

Seeded through ``apply_request(request)``, the generic store hook the framework
runs on every request path before anything reads store state (§6). That is what
buys a server-rendered page the real answer: no login flash, and no
fetch-on-mount waterfall.

A plain ``Store``, not an ``AppStateStore``: the state is request-derived, so
there is no ``project(app)`` to override. It is app-bound only because resolving
it needs the app's session getter and the plugin's resolved user model.

Seeding lives in ``apply_request`` and never in ``__init__``: the per-request
registry clear means this store is reconstructed from its blueprint for every
render, and a constructor that seeded would then be seeding from nothing.
"""

from basis.shared.store import Store


class AuthStore(Store):
    """The signed-in account, as the projection that may reach the wire.

    ``user`` carries the same shape ``GET /auth/session`` returns — never the
    model instance, and never a password hash — so the client and the server
    describe an account identically.
    """

    _requires_app = True
    user = None
    authenticated = False

    def __init__(self, name: str = "auth"):
        super().__init__(name)

    def apply_request(self, request) -> None:
        """Server-only: resolve this request's session cookie."""
        account = _resolve(request)
        self.user = account
        self.authenticated = account is not None


def _resolve(request):
    """The projection for the account behind *request*, or ``None``.

    ``db_session_var`` holds the request's database session, bound by the render
    pipeline *before* any store hook runs (§4.2 / D14). When it is absent there
    is nothing to look a session up in — an app with no session getter, or a path
    that does not bind one — and the request reads as anonymous rather than
    raising, because a page must still render. That is the same bargain
    ``ModelStore`` makes for its own server-side reads.
    """
    from basis.plugins.auth import sessions
    from basis.plugins.auth.models import user_projection
    from basis.shared.context import db_session_var

    db = db_session_var.get()
    if db is None:
        return None

    plugin = _auth_plugin(request.app)
    if plugin is None or plugin.user_model is None:
        return None

    row = sessions.resolve_session(db, request.cookies.get(plugin._config()["cookie_name"]))
    if row is None:
        return None

    user = db.get(plugin.user_model, row.user_id)
    if user is None or not user.is_active:
        return None
    return user_projection(user)


def _auth_plugin(app):
    """The auth plugin registered on *app*, or ``None``.

    The store's state is request-derived rather than an app projection, so this
    lookup is the one thing it cannot derive: the plugin owns the cookie name and
    the user model that was resolved for this app. Matched by type rather than by
    name, so a renamed (or second) registration still resolves.
    """
    from basis.plugins.auth.plugin import AuthPlugin

    for registration in getattr(app, "_plugin_registrations", {}).values():
        if not getattr(registration, "disposed", False) and isinstance(
            registration.plugin, AuthPlugin
        ):
            return registration.plugin
    return None
