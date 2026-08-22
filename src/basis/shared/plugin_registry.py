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
from basis.shared.store import Store


def _plugin_listing(app) -> dict:
    """Build the plugin registry listing from an app's registrations.

    ``{name: {state, prefix, actions, requires}}`` over ``app._plugin_registrations``,
    including disabled plugins (state ``"disabled"``) so a manager can offer
    re-enable. Single source of truth shared by the ``$plugins`` store's
    refresh, the ``GET /basis/api/plugins`` endpoint, and any tooling.
    """
    registrations = getattr(app, "_plugin_registrations", {})
    snapshot = {}
    for pname, reg in registrations.items():
        plugin = reg.plugin
        snapshot[pname] = {
            "state": "disabled" if reg.disposed else "enabled",
            "prefix": getattr(plugin, "prefix", ""),
            "actions": sorted(getattr(plugin, "actions", {}) or {}),
            "requires": list(getattr(plugin, "requires", []) or []),
        }
    return snapshot


class PluginRegistryStore(Store):
    """Reactive, app-global plugin registry (registered under the name ``plugins``).

    Non-reactive wiring: ``_app`` (the owning :class:`Basis` app) is attached
    server-side by the app / SSR collector / action handler — app-bound stores
    opt in via the ``_requires_app`` class attribute. On the client ``_app`` is
    ``None`` and the store is a pure reactive view.
    """

    _requires_app = True

    def __init__(self, name: str = "plugins"):
        super().__init__(name)
        # Reactive projection: {plugin_name: {state, prefix, actions, requires}}.
        # Never clobber the SSR-hydrated items (see the store-subclass footgun).
        if not getattr(self, "_hydrated_from_ssr", False):
            self.__dict__["items"] = {}

    def _require_app(self):
        app = self.__dict__.get("_app")
        if app is None:
            raise RuntimeError(
                "PluginRegistryStore requires the owning Basis app (server-side). "
                "This is a client-facing RPC surface; call app.remove_plugin / "
                "app.enable_plugin directly on the server."
            )
        return app

    def _refresh_from_app(self) -> None:
        """Recompute ``items`` as a listing of the app's plugin registrations."""
        app = self.__dict__.get("_app")
        if app is None:
            return
        self.__dict__["items"] = _plugin_listing(app)

    def serialize(self) -> dict:
        self._refresh_from_app()
        return super().serialize()

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

    @server_action
    async def refresh(self) -> dict:
        """Re-sync the projection from the server (client → server RPC).

        On the client the store has no ``_app``, so on a CSR page (no SSR
        initial state) ``items`` starts empty. This action pulls the
        authoritative projection from the server; the RPC layer also applies it
        as ``new_state`` so ``$plugins.items`` updates reactively.
        """
        app = self._require_app()
        self._refresh_from_app()
        return {"ok": True, "items": self.__dict__.get("items", {})}


def ensure_plugin_registry() -> PluginRegistryStore:
    """Return the plugin registry store, creating it if absent.

    Called by the client entrypoints so ``$plugins`` resolves on every page.
    On SSR pages the store hydrates from ``#basis-initial-state`` (the listing
    is already present); on CSR pages the page shell embeds the authoritative
    listing the same way (see ``Page._prepare_full_page``). No client fetch is
    needed — ``refresh()`` exists for on-demand re-sync.
    """
    from basis.shared.store import ensure_store

    return ensure_store("plugins", PluginRegistryStore)
