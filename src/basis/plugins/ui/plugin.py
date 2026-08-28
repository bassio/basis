"""The official UI plugin — Basis's built-in component suite.

Formerly the framework-core ``basis.ui`` package, mounted unconditionally at
``/basis/ui/`` by ``bootstrap``. Now a plugin: it self-serves its component
files to the client (via ``static_dir`` / ``static_mount``) and is registered
through the standard ``basis.plugins`` entry point, exactly like any
third-party plugin — so apps can also opt out of the component library by
excluding the ``ui`` plugin.

Component families live directly under the plugin package (one directory per
family, e.g. ``button/``). Theming is no longer part of this plugin — the
token schema, ``ThemeStore`` and ``<ui-theme-provider>`` moved to the official
``basis.plugins.theme`` plugin (ROADMAP-THEMING.md), which this plugin depends
on (``requires=["theme"]``). The plugin itself carries no HTTP routes and no
boot-time store wiring: components are imported by app code (which registers
their custom elements), and the ``$theme`` store is wired by the theme plugin
(plus the app's own conventional ``stores/`` layout) — unchanged from the
pre-migration behaviour.
"""

from pathlib import Path

from basis.shared.plugin import BasisPlugin


class UiPlugin(BasisPlugin):
    """The built-in UI component suite plugin.

    ``on_register`` is intentionally a no-op: the plugin exists to *serve* the
    component files (so the client VFS can import ``basis.plugins.ui.*``) and
    to appear in the plugin registry like any other plugin. Components are
    imported by app code, and the ``$theme`` store is wired by the theme
    plugin + the app's own stores/ auto-discovery.
    """

    def on_register(self, app) -> None:
        pass


# The module-level plugin instance (entry-point convention: a module-level
# ``plugin`` variable that is a ``BasisPlugin`` instance).
plugin = UiPlugin(
    prefix="",
    static_dir=Path(__file__).parent,
    static_mount="/basis/plugins/ui",
    name="ui",
    tags=None,
    requires=["theme"],
)
