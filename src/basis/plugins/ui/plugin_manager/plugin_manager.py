"""Live plugin manager panel bound to the ``$plugins`` registry store.

Lists every registered plugin with its state, prefix, action count and
dependencies, and provides a per-plugin toggle that calls the store's server
actions (``$plugins.disable(name)`` / ``$plugins.enable(name)``) so the plugin
is actually unmounted/remounted server-side (routes, mounts, models, actions)
and the panel re-renders from the authoritative ``new_state``.

The panel reads ``$plugins.items`` directly in the template, so it is reactive
from the start: toggling a plugin re-renders its row live, and the whole list
reflects the current registry.
"""

from basis.plugins.ui.registry_manager.registry_manager import RegistryManager


class PluginManager(RegistryManager):
    """
    A live plugin manager panel bound to the app's ``$plugins`` registry store.

    A thin ``RegistryManager`` face (``registry="plugins"``): the shared base
    renders the reactive rows and dispatches the row action; this class only
    adds the store name and the per-row disable/enable toggle. The theme
    manager (``<ui-theme-picker>``) is the sibling face over ``$themes``
    (ROADMAP-THEMING.md §6.5.4). Themes (``kind == "theme"``) are filtered out
    of ``$plugins.items`` by the shared registry listing — they appear only in
    the theme manager.
    """
    __tag__ = "ui-plugin-manager"
    registry = "plugins"

    def primary_action(self, name, info):
        """Disable or enable the plugin named by ``data-name`` on the row.

        The disable/enable action returns the fresh registry listing (when the
        regions plugin is active), which the client RPC layer applies to the
        stores automatically — so this panel does not need to know about
        regions or themes at all.
        """
        store = self.S.get("plugins")
        if store is None:
            return
        import asyncio
        if info.get("state") == "enabled":
            asyncio.ensure_future(store.disable(name))
        else:
            asyncio.ensure_future(store.enable(name))

    def template(self):
        """
        <div class="ui-registry-manager">
            <div class="ui-registry-manager-head">
                <span class="ui-registry-manager-title">Plugins</span>
                <span class="ui-registry-manager-count">{len($plugins.items)}</span>
            </div>
            <div class="ui-registry-manager-list">
                <div class="ui-registry-manager-row" for="entry" in="{$plugins.items.items()}">
                    <div class="ui-registry-manager-main">
                        <span class="ui-registry-manager-name">{entry[0]}</span>
                        <span class="ui-registry-manager-state {entry[1]['state']}">{entry[1]['state']}</span>
                    </div>
                    <div class="ui-registry-manager-meta">
                        <span>{len(entry[1]['actions'])} action(s)</span>
                        <span>requires: {requires_text(entry[1])}</span>
                    </div>
                    <button class="ui-registry-manager-toggle" onclick="{toggle}" data-name="{entry[0]}">
                        {button_label(entry[1])}
                    </button>
                </div>
            </div>
        </div>
        """
