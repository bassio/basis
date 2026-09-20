"""The auth tables — server-only, imported lazily by the plugin.

Everything the client needs is in ``plugin.py`` / ``crypto.py`` / ``tokens.py``;
this module imports ``sqlmodel``, so it must never reach the served package's
module-scope imports.

``UserFields`` is the extension point (§4.1): the columns every user model
shares, with no table and no relationships of its own. That is what lets the two
shipped models be *siblings* over it rather than parent and child — a
``table=True`` subclass of a ``table=True`` class silently reuses the parent's
table and drops its own columns, so inheritance cannot express them.
"""

import json
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Field, SQLModel

#: The table the plugin's user model maps, and the target ``AuthSession.user_id``
#: pins its foreign key to. Prefixed, so that installing auth cannot claim a
#: global name an app may already be using: the plugin owns the ``auth_``
#: namespace and nothing else. An app bringing its own user model maps this
#: name — the class and the column set stay its own choice — and that static
#: foreign key is what lets ``Relationship()`` resolve at all.
USER_TABLE = "auth_user"
SESSION_TABLE = "auth_session"
LOGIN_ATTEMPT_TABLE = "auth_login_attempt"


def utcnow() -> datetime:
    """Naive UTC, so a stored timestamp never mixes naive and aware datetimes."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class UserFields(SQLModel):
    """The user columns, shared by every user model.

    Not a table itself: it is both the app's extension point and the type the
    plugin's own code is written against, so internals never need to know which
    concrete model the app chose.
    """

    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    password_hash: str = ""
    display_name: str | None = None
    is_active: bool = True
    is_superuser: bool = False
    #: A JSON array of role names (D7) — no join table for a list this small.
    roles: str = "[]"
    created_at: datetime = Field(default_factory=utcnow)


class AuthSession(SQLModel, table=True):
    """One logged-in session, as a row — so revocation is real (D3)."""

    __tablename__ = SESSION_TABLE

    id: int | None = Field(default=None, primary_key=True)
    #: SHA-256 of the cookie value: a database read cannot mint a session.
    token_hash: str = Field(index=True, unique=True)
    user_id: int = Field(foreign_key=f"{USER_TABLE}.id", index=True)
    created_at: datetime = Field(default_factory=utcnow)
    expires_at: datetime
    last_seen_at: datetime = Field(default_factory=utcnow)
    user_agent: str | None = None
    ip: str | None = None


class LoginAttempt(SQLModel, table=True):
    """Throttle/lockout state, as a row rather than a module-level dict (D13).

    In-process state would be per-worker, and therefore silently wrong behind
    ``uvicorn --workers N``.
    """

    __tablename__ = LOGIN_ATTEMPT_TABLE

    #: ``f"{ip}|{email}"`` — counted for unknown emails too, so the throttle is
    #: not itself an account-existence oracle.
    key: str = Field(primary_key=True)
    count: int = 0
    window_start: datetime = Field(default_factory=utcnow)
    locked_until: datetime | None = None


def parse_roles(roles: str | None) -> list[str]:
    """Roles as a list. A malformed column reads as no roles — never an error
    on a request path."""
    try:
        parsed = json.loads(roles or "[]")
    except ValueError:
        return []
    if not isinstance(parsed, list):
        return []
    return [role for role in parsed if isinstance(role, str)]


def user_projection(user: UserFields) -> dict[str, Any]:
    """The user shape that may reach the wire.

    ``password_hash`` is absent by construction, and ``model_dump()`` is
    deliberately not the way to build this: a column added later must not become
    public by default.
    """
    return {
        "id": user.id,
        "email": user.email,
        "display_name": user.display_name,
        "is_active": user.is_active,
        "is_superuser": user.is_superuser,
        "roles": parse_roles(user.roles),
        "created_at": user.created_at.isoformat() if user.created_at else None,
    }
