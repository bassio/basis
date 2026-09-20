"""The auth plugin — identity and sessions, installed rather than built in.

Registered through the standard ``basis.plugins`` entry point, so it rides the
same discovery and lifecycle as any third-party plugin: no ``on_register``
special case in core, no auth concept outside this package.

This module must stay client-safe — the package is served to the browser at
``/basis/plugins/auth``, so everything imported here must import in PyScript
too. ``routes.py`` qualifies (its server-only imports sit inside handler bodies);
the modules that could not — ``models.py``, ``sessions.py`` — are imported inside
the functions that need them, never at module scope.

The HTTP surface sits at ``/auth`` while the package is served from
``/basis/plugins/auth``. The two are separate on purpose: a plugin's ``prefix``
is its public API, whereas ``serving_mount`` has to reproduce the package path so
the client VFS namespace matches the filesystem — the half the isomorphism guard
enforces.
"""

import importlib
import sys
from pathlib import Path
from typing import Any

from basis.shared.plugin import BasisPlugin

from basis.plugins.auth.routes import declare_routes


class AuthConfigError(RuntimeError):
    """A misconfiguration this plugin refuses to guess around.

    Raised from ``on_register`` so a bad setting fails at boot with a named
    cause, instead of as a 500 at the first login.
    """


#: ``configure(user_model=…)`` accepts one of these shipped names, or a class.
SHIPPED_USER_MODELS: dict[str, tuple[str, str]] = {
    "bare": ("basis.plugins.auth.models_bare", "User"),
    "relations": ("basis.plugins.auth.models_relations", "UserWithRelations"),
}

DEFAULT_USER_MODEL = "bare"

_DEFAULTS: dict[str, Any] = {
    "user_model": DEFAULT_USER_MODEL,
    "cookie_name": "basis_session",
    #: 14 days, sliding: a session in use does not time out.
    "session_ttl": 60 * 60 * 24 * 14,
    "trust_proxy": False,
    "allow_registration": False,
    "password_min_length": 8,
    "password_check": None,
    #: Failed logins per ``ip|email`` before the key is locked. ``duration``
    #: should be at least ``window`` — a lock that expires while its own window
    #: is still open relocks on the next mistake.
    "lockout_threshold": 5,
    "lockout_window": 300,
    "lockout_duration": 900,
    #: Password reset needs all three, and none has a safe default: a transport
    #: to deliver the link, a secret to sign the token with, and the app's public
    #: origin to build the link from. See ``routes._reset_blocker``.
    "mailer": None,
    "secret_key": None,
    "public_url": None,
    "reset_path": "/reset-password",
    "reset_token_ttl": 3600,
}


class AuthPlugin(BasisPlugin):
    """The auth mechanism plugin: users, sessions and the tables behind them.

    ``on_register`` resolves exactly one user model and registers the plugin's
    tables; the HTTP surface under ``/auth`` is declared as the instance is
    built, because a plugin's router is copied into the app only once. Later
    phases add the store, the guards, the components and the CLI — each as
    another declaration here, so unwinding the plugin stays the framework's
    ordinary revertible lifecycle.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        #: The concrete user model, resolved in ``on_register`` (§4.1).
        self.user_model: type | None = None
        declare_routes(self)

    # -- configuration ------------------------------------------------------

    def configure(self, **settings) -> "AuthPlugin":
        """Apply app settings; returns ``self`` so it chains onto registration.

        Declared here rather than inherited because the client ``BasisPlugin``
        shim carries no ``configure`` — the plugin's config surface has to look
        the same from both sides of the isomorphism boundary. Values are
        validated where they are used, not on the way in.
        """
        self._settings.update(settings)
        return self

    def _config(self) -> dict[str, Any]:
        """The effective settings — the single place settings are read."""
        return {**_DEFAULTS, **self._settings}

    # -- lifecycle ----------------------------------------------------------

    def on_register(self, app) -> None:
        """Resolve the app's user model, register its tables, wire ``$auth``.

        Deliberately does not demand ``app.get_session``. Auth is installed in
        every app that has the package, including apps with no database at all,
        so requiring a session getter here would break those apps at boot. The
        check belongs where a session is first genuinely needed, which puts the
        failure on the app that *uses* auth rather than on one that merely
        ships it.

        ``$auth`` goes in through ``include_store`` — the same call the regions
        and theme plugins make — so it is a first-class app store: collected by
        both engines, and unwound by the ordinary revertible lifecycle.
        """
        from basis.plugins.auth import models
        from basis.plugins.auth.store import AuthStore

        self.user_model = self._resolve_user_model()
        for table in (models.AuthSession, models.LoginAttempt, self.user_model):
            self.model(table)

        store = self.include_store(app, AuthStore, "auth")
        if not hasattr(app, "auth"):
            app.auth = store

    # -- user model resolution ---------------------------------------------

    def _resolve_user_model(self) -> type:
        """The one concrete user model this app uses (§4.1).

        A class is the app's own model; a name selects a shipped variant.
        """
        from sqlmodel import SQLModel

        from basis.plugins.auth.models import USER_TABLE

        configured = self._config()["user_model"]

        if isinstance(configured, type):
            return self._validate_user_model(configured)

        if configured not in SHIPPED_USER_MODELS:
            raise AuthConfigError(
                f"user_model={configured!r} is neither a shipped variant "
                f"{sorted(SHIPPED_USER_MODELS)} nor a user model class. Pass one "
                f"of those names, or your own UserFields subclass."
            )

        # Skipping the shipped import when the app already mapped the table
        # would silently make "which model am I using?" depend on import order.
        # Refuse instead, before SQLAlchemy's own "Table 'auth_user' is already
        # defined" — loud, but it does not name this fix — can surface two
        # frames deeper.
        module_path, attr = SHIPPED_USER_MODELS[configured]
        # An already-loaded variant is no conflict: its classes are the ones
        # holding the mapped table, and importing it again is a no-op. Only a
        # table mapped while the module has *not* been loaded can belong to
        # another model — which is what makes this check reliable rather than a
        # guess about import order.
        module = sys.modules.get(module_path)
        if module is None:
            if USER_TABLE in SQLModel.metadata.tables:
                raise AuthConfigError(
                    f"user_model={configured!r} cannot be imported: a table named "
                    f"{USER_TABLE!r} is already mapped by another model — your "
                    f"app's own, or the other shipped variant. Select that model "
                    f"explicitly with configure(user_model=<that class>)."
                )
            module = importlib.import_module(module_path)
        return self._validate_user_model(getattr(module, attr))

    @staticmethod
    def _validate_user_model(model: type) -> type:
        """Fail loudly unless *model* is a mapped ``user`` table (§4.1).

        Checked here rather than at the first query: a model mapping the wrong
        table otherwise surfaces as a foreign-key error from ``AuthSession`` at
        login time, where the cause is nowhere near the symptom.
        """
        from sqlmodel import SQLModel

        from basis.plugins.auth.models import USER_TABLE, UserFields

        name = getattr(model, "__name__", model)
        if not (isinstance(model, type) and issubclass(model, UserFields)):
            raise AuthConfigError(
                f"user_model={name!r} must be a UserFields subclass — either a "
                f"shipped variant or your own class declaring "
                f"__tablename__ = {USER_TABLE!r}."
            )
        if SQLModel.metadata.tables.get(USER_TABLE) is not getattr(model, "__table__", None):
            raise AuthConfigError(
                f"user_model={name!r} does not map a table named {USER_TABLE!r}, "
                f"which AuthSession's foreign key targets. Declare "
                f"`class {name}(UserFields, table=True)` with "
                f"__tablename__ = {USER_TABLE!r}, or select a shipped variant."
            )
        return model


plugin = AuthPlugin(
    prefix="/auth",
    serving_dir=Path(__file__).parent,
    serving_mount="/basis/plugins/auth",
    name="auth",
)
