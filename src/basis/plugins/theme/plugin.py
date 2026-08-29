"""The official theme plugin — the theming mechanism (ROADMAP-THEMING.md).

Sibling to ``regions`` / ``ui`` / ``shell`` on the standard ``basis.plugins``
entry point. It provides:

- the ``$theme`` store (``ThemeStore``), wired into the app in ``on_register``
  via ``include_store`` (the regions pattern) so ``$theme`` resolves on every
  page — an app's own ``stores/`` theme (possibly a ``ThemeStore`` subclass)
  wins because the blueprint is reused,
- the ``$themes`` catalog store (``ThemeRegistryStore``) — the theme slice of
  the shared registry (``kind == "theme"``) that the theme manager renders,
- the token schema (``ThemeDefinition`` / ``ThemeTokens``), the ``Theme``
  plugin base, and the built-in ``basis`` default theme,
- the ``<ui-theme-provider>`` element (served to the client via ``serving_dir``).

The ``ui`` and ``shell`` plugins depend on it (``requires=["theme"]``); the
default theme is a separate ``Theme`` entry point (``kind="theme"``) that rides
the identical path as community themes (ROADMAP-THEMING §6.5.1).
"""

from pathlib import Path

from basis.shared.plugin import BasisPlugin, Request
from basis.plugins.theme.store import ThemeStore
from basis.plugins.theme.registry import ThemeRegistryStore


class ThemePlugin(BasisPlugin):
    """The theme mechanism plugin (``kind="plugin"``, framework-essential).

    ``on_register`` wires the ``$theme`` + ``$themes`` stores into the app:
    ``include_store`` reuses the app's blueprints when they exist (an app may
    subclass ``ThemeStore`` in its ``stores/``), otherwise it constructs the
    defaults so both stores always resolve. ``$theme`` is app-bound
    (``_requires_app``) so ``set_theme`` can resolve definitions server-side;
    ``$themes`` is an ``AppStateStore`` projection like ``$plugins``.
    """

    def on_register(self, app) -> None:
        self.include_store(app, ThemeStore, "theme")
        self.include_store(app, ThemeRegistryStore, "themes")


plugin = ThemePlugin(
    prefix="",
    serving_dir=Path(__file__).parent,
    serving_mount="/basis/plugins/theme",
    name="theme",
    tags=None,
    requires=[],
)


@plugin.router.get("/basis/api/themes")
async def _themes_projection(request: Request):
    """Projection endpoint mirroring ``/basis/api/plugins`` — the theme catalog.

    ``Request`` comes from the client/server shim (``basis.shared.plugin``), so
    this module imports cleanly on the client too; the server-only
    ``fastapi.responses`` import stays inside the handler.
    """
    from fastapi.responses import JSONResponse
    from basis.shared.plugin_registry import _registry_listing

    return JSONResponse(_registry_listing(request.app, kinds=("theme",)))

