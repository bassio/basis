"""App-global plugin registry store — the ``$plugins`` control plane.

The store is a *reactive projection* of the app's plugin registrations
(``Basis._plugin_registrations``). On the server it is server-authoritative:
``disable`` / ``enable`` are store-bound server actions that perform the real
revertible unregistration (``app.remove_plugin`` / ``app.enable_plugin``) and
return authoritative ``new_state``. On the client it is a pure reactive view
hydrated from ``#basis-initial-state`` (SSR and CSR pages both embed the
authoritative listing; ``refresh()`` gives on-demand re-sync), so components
bind to ``$plugins.*`` and re-render when plugin state changes.
On the server side, the relevant data is ``PluginRegistration`` records.
"""

from basis.shared.actions import server_action
from basis.shared.app_state import AppStateStore


def _registry_listing(app, kinds: tuple[str, ...] | None = None) -> dict:
    """Build the contribution registry listing from an app's registrations.

    ``{name: {kind, state, prefix, actions, requires, …}}`` over
    ``app._plugin_registrations``, optionally filtered by ``kinds``. Themes
    (``kind == "theme"``) additionally carry a ``theme`` metadata block. The
    single source of truth shared by the ``$plugins`` / ``$themes`` stores, the
    projection endpoints, and any tooling (ROADMAP-THEMING.md §6.5.2).
    """
    registrations = getattr(app, "_plugin_registrations", {})
    snapshot = {}
    for pname, reg in registrations.items():
        plugin = reg.plugin
        if kinds is not None and plugin.kind not in kinds:
            continue
        entry = {
            "kind": getattr(plugin, "kind", "plugin"),
            "state": "disabled" if reg.disposed else "enabled",
            "prefix": getattr(plugin, "prefix", ""),
            "actions": sorted(getattr(plugin, "actions", {}) or {}),
            "requires": list(getattr(plugin, "requires", []) or []),
            # The module that constructed the plugin (recorded at discovery) —
            # the client can import it to reach the plugin's live instance.
            "module": getattr(plugin, "_origin_module", None),
        }
        if entry["kind"] == "theme":
            # Theme metadata is theme-plugin territory — theme is its own
            # plugin, not a framework-core concern — so it is shaped in
            # ``basis.plugins.theme.registry`` and imported lazily here (keeps
            # framework core theme-agnostic at load time; works server + client
            # because the theme plugin's modules are client-served too).
            from basis.plugins.theme.registry import theme_metadata

            entry["theme"] = theme_metadata(plugin)
        snapshot[pname] = entry
    return snapshot


def _plugin_listing(app) -> dict:
    """The plugin-only listing (``kind == "plugin"``) — themes are excluded.

    Backward-compatible wrapper over :func:`_registry_listing`: the ``$plugins``
    store, the ``GET /basis/api/plugins`` endpoint, and tooling keep using this
    name; themes live in the ``$themes`` catalog instead (ROADMAP-THEMING.md).
    """
    return _registry_listing(app, kinds=("plugin",))


class PluginRegistryStore(AppStateStore):
    """Reactive, app-global plugin registry (registered under the name ``plugins``).

    An :class:`AppStateStore` whose ``items`` projection is the app's plugin
    registrations. Non-reactive wiring: ``_app`` (the owning :class:`Basis`
    app) is attached server-side by the app / SSR collector / action handler;
    on the client ``_app`` is ``None`` and the store is a pure reactive view.
    """

    def __init__(self, name: str = "plugins"):
        super().__init__(name)
        # Reactive projection: {plugin_name: {state, prefix, actions, requires}}.
        # Never clobber the SSR-hydrated items (see the store-subclass footgun).
        if not getattr(self, "_hydrated_from_ssr", False):
            self.__dict__["items"] = {}

    def project(self, app) -> dict:
        """Project the app's plugin registrations as the store's ``items``."""
        return {"items": _plugin_listing(app)}

    @server_action
    async def disable(self, name: str) -> dict:
        """Unmount a plugin (client-facing RPC entry point).

        Plugins imported by client modules are refused (``ok: False``) — the
        unload decision is server-side; the UI does not get a force option.
        """
        app = self._require_app()
        changed = await app.disable_plugin(name)
        return {"ok": changed}

    @server_action
    async def enable(self, name: str) -> dict:
        """Re-mount a previously disabled plugin (client-facing RPC entry point)."""
        app = self._require_app()
        changed = await app.enable_plugin(name)
        return {"ok": changed}



def ensure_plugin_registry() -> PluginRegistryStore:
    """Return the plugin registry store, creating it if absent.

    Called by the client entrypoints so ``$plugins`` resolves on every page.
    On SSR pages the store hydrates from ``#basis-initial-state`` (the listing
    is already present); on CSR pages the page shell embeds the authoritative
    listing the same way (see ``Page.render``). No client fetch is
    needed — ``refresh()`` exists for on-demand re-sync.
    """
    from basis.shared.store import ensure_store

    return ensure_store("plugins", PluginRegistryStore)
