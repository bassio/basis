"""The theme manager — ``<ui-theme-picker>`` (ROADMAP-THEMING.md §6.5.4).

A ``RegistryManager`` face over ``$themes`` (the theme catalog): lists every
installed theme (from the shared registry, ``kind == "theme"``) with its name,
modes and version, and lets the user apply one via ``$theme.set_theme(id)`` or
flip the mode via ``$theme.set_mode(...)``. Shares its row chrome, state badge
and action dispatch with the plugin manager (``<ui-plugin-manager>``).
"""

from basis.plugins.ui.registry_manager.registry_manager import RegistryManager


class ThemePicker(RegistryManager):
    """
    A live theme manager bound to the ``$themes`` catalog store.

    Rows project ``$themes.items`` reactively (the shared registry listing);
    the primary row action applies the theme (``$theme.set_theme(id)``), and the
    header button flips the mode (``$theme.set_mode(...)``). Both persist via
    the ``basis_theme`` cookie, so a reload keeps the choice — no FOUC.
    """
    __tag__ = "ui-theme-picker"
    registry = "themes"

    def primary_action(self, name, info):
        """Apply the theme named by ``data-name`` on the row."""
        theme = info.get("theme") or {}
        theme_id = theme.get("id") or name
        theme_store = self.S.get("theme")
        if theme_store is None:
            return
        # Client-side engine: synchronous local apply + cookie flush (no RPC).
        theme_store.set_theme(theme_id)

    def button_label(self, info):
        return "Apply"

    def toggle_mode(self, event):
        """Flip the color mode via the ``$theme.set_mode`` dual-path method."""
        theme_store = self.S.get("theme")
        if theme_store is None:
            return
        theme_store.set_mode("light" if getattr(theme_store, "dark_mode", False) else "dark")

    def mode_label(self):
        store = self.S.get("theme")
        return "Dark" if store is not None and getattr(store, "dark_mode", False) else "Light"

    def theme_name(self, info):
        return (info.get("theme") or {}).get("name") or "Theme"

    def theme_meta(self, info):
        theme = info.get("theme") or {}
        bits = []
        modes = theme.get("modes") or []
        if modes:
            bits.append("/".join(modes))
        version = theme.get("version")
        if version:
            bits.append(version)
        return " · ".join(bits) if bits else "—"

    def template(self):
        """
        <div class="ui-registry-manager">
            <div class="ui-registry-manager-head">
                <span class="ui-registry-manager-title">Themes</span>
                <span class="ui-registry-manager-count">{len($themes.items)}</span>
                <button class="ui-registry-manager-mode" onclick="{toggle_mode}" title="Toggle light/dark">{mode_label()}</button>
            </div>
            <div class="ui-registry-manager-list">
                <div class="ui-registry-manager-row" for="entry" in="{$themes.items.items()}">
                    <div class="ui-registry-manager-main">
                        <span class="ui-registry-manager-name">{theme_name(entry[1])}</span>
                        <span class="ui-registry-manager-state {entry[1]['state']}">{entry[1]['state']}</span>
                    </div>
                    <div class="ui-registry-manager-meta">
                        <span>{theme_meta(entry[1])}</span>
                    </div>
                    <button class="ui-registry-manager-toggle" onclick="{toggle}" data-name="{entry[0]}">
                        {button_label(entry[1])}
                    </button>
                </div>
            </div>
        </div>
        """
