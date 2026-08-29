"""The ``$themes`` catalog store — the theme registry (ROADMAP-THEMING §6.5.3).

An :class:`~basis.shared.app_state.AppStateStore` whose ``items`` projection is
the *theme* slice of the shared contribution registry (``kind == "theme"``) —
the sibling of ``$plugins``. ``$themes`` says what themes are available (and
their state); ``$theme`` says what's applied and how it looks.

The theme ``metadata`` block each catalog entry carries is shaped here too
(:func:`theme_metadata`) — theme is its own plugin, so this lives in the theme
plugin, not in framework-core's plugin registry. The shared registry listing
builder calls it lazily for ``kind == "theme"`` entries.
"""

from basis.shared.actions import server_action
from basis.shared.app_state import AppStateStore
from basis.shared.plugin_registry import _registry_listing


def theme_metadata(plugin) -> dict | None:
    """Metadata for a theme registration (``kind == "theme"``) for the catalog.

    Reads common fields off ``plugin.definition`` generically. Homed in the
    theme plugin (theme is its own plugin, not a framework-core concern); the
    shared ``_registry_listing`` builder imports it lazily for theme entries so
    framework core stays theme-agnostic (ROADMAP-THEMING.md §6.5.2).
    """
    definition = getattr(plugin, "definition", None)
    if definition is None:
        return None
    scheme = getattr(definition, "color_scheme", "auto") or "auto"
    modes = ["light", "dark"] if scheme in ("auto", "system") else [scheme]
    return {
        "id": getattr(definition, "id", None),
        "name": getattr(definition, "name", None),
        "version": getattr(definition, "version", None),
        "author": getattr(definition, "author", None),
        "modes": modes,
        "preview": getattr(definition, "preview", None),
        # The module where the theme's ``plugin`` instance lives (recorded at
        # discovery) — the client imports it to get the live definition.
        "module": getattr(plugin, "_origin_module", None),
    }


class ThemeRegistryStore(AppStateStore):
    """Reactive, app-global theme catalog (registered under the name ``themes``).

    Same shape as the ``$plugins`` registry store: an ``items`` projection of
    the shared registry, SSR-serialized, client-reactive. The only differences
    are the ``kind == "theme"`` filter and the theme metadata block each entry
    carries (ROADMAP-THEMING §6.5.2).
    """

    def __init__(self, name: str = "themes"):
        super().__init__(name)
        # Never clobber the SSR-hydrated items (see the store-subclass footgun).
        if not getattr(self, "_hydrated_from_ssr", False):
            self.__dict__["items"] = {}

    def project(self, app) -> dict:
        """Project the app's *theme* registrations as the store's ``items``."""
        return {"items": _registry_listing(app, kinds=("theme",))}

    @server_action
    async def disable(self, name: str) -> dict:
        """Unmount a theme plugin (the app falls back to the default on the
        next render). Same revertible machinery as ``$plugins.disable``."""
        app = self._require_app()
        changed = await app.disable_plugin(name)
        return {"ok": changed}

    @server_action
    async def enable(self, name: str) -> dict:
        """Re-mount a previously disabled theme plugin."""
        app = self._require_app()
        changed = await app.enable_plugin(name)
        return {"ok": changed}


def ensure_theme_registry() -> ThemeRegistryStore:
    """Return the ``$themes`` store, creating it if absent (client entrypoints)."""
    from basis.shared.store import ensure_store

    return ensure_store("themes", ThemeRegistryStore)
