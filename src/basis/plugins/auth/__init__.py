"""The auth plugin — users, sessions and the guard hooks around them.

Only the client-safe surface is re-exported. The model modules import
``sqlmodel``, so importing this package must never reach them — the package is
served to the browser at ``/basis/plugins/auth``.
"""

from basis.plugins.auth.plugin import AuthConfigError, AuthPlugin, plugin

__all__ = ["AuthConfigError", "AuthPlugin", "plugin"]
