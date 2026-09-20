"""The shipped user model with relationships (§4.1): the same table, plus
``sessions`` reachable from the user.

Imported only when ``configure(user_model="relations")`` selects it. The
relationship is declared here, on the concrete model, rather than on
``UserFields``: which relationships a user model carries is exactly the choice
the two shipped models exist to offer, and a relationship on the shared mixin
would impose the session table on every app.
"""

from sqlmodel import Relationship

from basis.plugins.auth.models import USER_TABLE, AuthSession, UserFields


class UserWithRelations(UserFields, table=True):
    """The shipped user model that can navigate to its sessions."""

    __tablename__ = USER_TABLE

    sessions: list[AuthSession] = Relationship()
