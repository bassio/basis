"""Phase 1b — the tables, the two shipped user models, and ``on_register``.

``SQLModel.metadata`` is process-global and a table name can be mapped only
once, so every scenario that maps the ``user`` table runs in its own
interpreter (the same discipline ``test_isomorphism.py`` uses for ``sys.modules``).
The scenarios below are therefore scripts, driven through :func:`_run`.

The gate this file holds: an app picks a user model, ``on_register`` resolves
exactly that one, the tables are created from it, rows round-trip, and every way
of getting the choice wrong fails at boot with a named cause.
"""

import subprocess
import sys
import textwrap

from sqlmodel import SQLModel

from basis.plugins.auth import models
from basis.plugins.auth.models import AuthSession, UserFields, user_projection

# Imported for its mapping, not its class: ``auth_session.user_id`` carries a
# foreign key to ``auth_user``, so importing the tables without a user model
# would leave SQLAlchemy unable to configure mappers for any later test sharing
# this process. The plugin cannot be in that state — ``on_register`` always
# resolves a user model — so the default variant stands in here.
from basis.plugins.auth.models_bare import User  # noqa: F401

_PRELUDE = """\
import sys
from datetime import datetime, timedelta

from sqlmodel import Field, SQLModel, Session, create_engine, select

from basis.plugins.auth import AuthConfigError, plugin as auth_plugin
from basis.server.app import Basis


def boot(app=None):
    app = app or Basis()
    app.include_plugin(auth_plugin)
    return app


def db(app):
    engine = create_engine("sqlite://")
    app.create_db_and_tables(engine)
    return engine


def expires():
    return datetime.utcnow() + timedelta(hours=1)
"""


#: Appended to a scenario body by :func:`_refuses`. Column 0 so it survives the
#: body's own ``dedent`` unchanged.
_REFUSE = """
try:
    boot()
except AuthConfigError as exc:
    print("AuthConfigError:", exc)
else:
    raise SystemExit("expected AuthConfigError, got a registered plugin")
"""


def _run(body: str) -> str:
    """Run *body* in a fresh interpreter, asserting it succeeds."""
    result = subprocess.run(
        [sys.executable, "-c", _PRELUDE + textwrap.dedent(body)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"scenario failed:\n--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
    )
    return result.stdout


def _refuses(body: str) -> str:
    """Run *body* and return the message of the ``AuthConfigError`` it raised."""
    # Dedent before appending: ``_REFUSE`` sits at column 0, which would pin the
    # combined script's common indentation to zero and leave the body indented.
    output = _run(textwrap.dedent(body) + _REFUSE)
    assert "AuthConfigError:" in output, output
    return output


# ── the default: the bare variant, in an app with no database ──────────────


def test_default_selects_the_bare_variant_and_boots_without_a_database():
    """Auth is installed in DB-less apps too, so registration must not demand
    ``app.get_session`` — the check belongs where a session is used."""
    output = _run(
        """
        import basis.plugins.auth.models as models
        # Imported *before* boot on purpose: an app may hold the class to
        # compare against, and a pre-loaded variant must not be mistaken for a
        # competing user model.
        from basis.plugins.auth.models_bare import User

        app = Basis()
        assert getattr(app, "get_session", None) is None, "scenario is meant to be DB-less"

        boot(app)

        assert auth_plugin.user_model is User
        assert auth_plugin.models == {models.AuthSession, models.LoginAttempt, User}
        assert "sessions" not in User.__dict__, "the bare variant carries no relationships"
        assert "basis.plugins.auth.models_relations" not in sys.modules, (
            "the unselected variant must never be imported"
        )
        print("OK")
        """
    )
    assert "OK" in output


def test_bare_variant_creates_the_tables_and_round_trips():
    output = _run(
        """
        import basis.plugins.auth.models as models
        from basis.plugins.auth.models_bare import User

        engine = db(boot())

        assert {"auth_user", "auth_session", "auth_login_attempt"} <= set(SQLModel.metadata.tables)

        with Session(engine) as session:
            user = User(email="a@b.c", password_hash="hashed")
            session.add(user)
            session.commit()
            session.refresh(user)
            session.add(
                models.AuthSession(token_hash="t", user_id=user.id, expires_at=expires())
            )
            session.commit()

            loaded = session.get(User, user.id)
            assert loaded.email == "a@b.c"
            assert loaded.password_hash == "hashed"
            assert session.exec(select(models.AuthSession)).one().user_id == user.id
        print("OK")
        """
    )
    assert "OK" in output


# ── the relations variant ─────────────────────────────────────────────────


def test_relations_variant_navigates_to_its_sessions():
    output = _run(
        """
        import basis.plugins.auth.models as models
        from basis.plugins.auth.models_relations import UserWithRelations

        auth_plugin.configure(user_model="relations")
        engine = db(boot())

        assert auth_plugin.user_model is UserWithRelations
        assert "sessions" in UserWithRelations.__dict__
        assert "basis.plugins.auth.models_bare" not in sys.modules, (
            "the unselected variant must never be imported"
        )

        with Session(engine) as session:
            user = UserWithRelations(email="a@b.c", password_hash="hashed")
            session.add(user)
            session.commit()
            session.refresh(user)
            session.add(
                models.AuthSession(token_hash="t", user_id=user.id, expires_at=expires())
            )
            session.commit()
            session.expire_all()

            loaded = session.get(UserWithRelations, user.id)
            assert [row.token_hash for row in loaded.sessions] == ["t"]
        print("OK")
        """
    )
    assert "OK" in output


# ── the app's own model (§4.1) ────────────────────────────────────────────


def test_app_supplied_model_is_used_and_imports_no_shipped_variant():
    output = _run(
        """
        from basis.plugins.auth.models import USER_TABLE, UserFields

        class Account(UserFields, table=True):
            __tablename__ = USER_TABLE
            nickname: str = ""

        auth_plugin.configure(user_model=Account)
        engine = db(boot())

        assert auth_plugin.user_model is Account
        assert "basis.plugins.auth.models_bare" not in sys.modules
        assert "basis.plugins.auth.models_relations" not in sys.modules
        assert "nickname" in Account.__table__.columns

        with Session(engine) as session:
            session.add(Account(email="a@b.c", password_hash="hashed", nickname="al"))
            session.commit()
            stored = session.exec(select(Account)).one()
            assert stored.nickname == "al"
        print("OK")
        """
    )
    assert "OK" in output


def test_app_model_without_explicit_configuration_is_refused():
    """The default variant cannot be imported over an app-declared ``user``
    table, and picking silently would make the choice depend on import order."""
    output = _refuses(
        """
        from basis.plugins.auth.models import USER_TABLE, UserFields

        class Account(UserFields, table=True):
            __tablename__ = USER_TABLE
        """
    )
    assert "already mapped" in output
    assert "configure(user_model=" in output


# ── every wrong choice fails at boot with a named cause ───────────────────


def test_model_that_does_not_map_the_user_table_is_refused():
    output = _refuses(
        """
        from basis.plugins.auth.models import UserFields

        class Wrong(UserFields, table=True):
            __tablename__ = "accounts"

        auth_plugin.configure(user_model=Wrong)
        """
    )
    assert "does not map a table named 'auth_user'" in output
    assert "AuthSession" in output


def test_class_that_is_not_a_userfields_subclass_is_refused():
    output = _refuses(
        """
        class NotAUser(SQLModel, table=True):
            __tablename__ = "not_a_user"
            id: int | None = Field(default=None, primary_key=True)

        auth_plugin.configure(user_model=NotAUser)
        """
    )
    assert "must be a UserFields subclass" in output


def test_unknown_user_model_name_is_refused():
    output = _refuses(
        """
        auth_plugin.configure(user_model="fancy")
        """
    )
    assert "is neither a shipped variant" in output
    assert "'bare'" in output and "'relations'" in output


# ── the package stays importable without the server-only dependency ───────


def test_importing_the_package_never_pulls_in_sqlmodel():
    """The package is served to the browser, so importing it must not reach
    ``models.py`` — the modules that import ``sqlmodel`` stay behind
    ``on_register``."""
    output = _run(
        """
        sys.modules["sqlmodel"] = None          # the browser has no sqlmodel

        import basis.plugins.auth as auth

        assert auth.plugin.name == "auth"
        assert auth.AuthPlugin is not None
        assert "basis.plugins.auth.models" not in sys.modules
        assert "basis.plugins.auth.models_bare" not in sys.modules
        assert "basis.plugins.auth.models_relations" not in sys.modules
        print("OK")
        """
    )
    assert "OK" in output


# ── the pieces that need no database session ─────────────────────────────


def test_userfields_is_a_mixin_not_a_table():
    assert getattr(UserFields, "__table__", None) is None


def test_session_foreign_key_targets_the_user_table():
    """The static foreign key is what lets ``Relationship()`` resolve at all,
    so the table name is part of the model contract (§4.1)."""
    (foreign_key,) = AuthSession.__table__.c.user_id.foreign_keys
    assert foreign_key.target_fullname == f"{models.USER_TABLE}.id"


def test_projection_never_carries_the_password_hash():
    user = UserFields(id=1, email="a@b.c", password_hash="hashed", roles='["admin"]')
    projection = user_projection(user)

    assert "password_hash" not in projection
    assert projection["email"] == "a@b.c"


def test_projection_omits_columns_the_app_added():
    """``model_dump()`` would publish them by default; the projection is
    deliberately an allowlist."""
    class Extended(UserFields):
        api_key: str = "secret"

    projection = user_projection(Extended(email="a@b.c"))
    assert "api_key" not in projection


def test_projection_carries_roles_as_a_list():
    projection = user_projection(UserFields(email="a@b.c", roles='["admin", "editor"]'))
    assert projection["roles"] == ["admin", "editor"]


def test_malformed_roles_read_as_no_roles():
    """A corrupt column must not raise on a request path."""
    for value in ("", "not json", '{"admin": true}', '["admin", 3]'):
        projection = user_projection(UserFields(email="a@b.c", roles=value))
        assert projection["roles"] in ([], ["admin"]), value
