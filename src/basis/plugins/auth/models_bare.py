"""The default shipped user model — columns only, no relationships (§4.1).

Imported only when ``configure(user_model="bare")`` (the default) selects it,
so an app that brings its own model never pays for this module.
"""

from basis.plugins.auth.models import USER_TABLE, UserFields


class User(UserFields, table=True):
    """The shipped user model: the mixin's columns and nothing else."""

    __tablename__ = USER_TABLE
