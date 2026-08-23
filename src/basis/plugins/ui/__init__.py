"""Official UI plugin — Basis's built-in component suite.

Moved out of the framework core (``basis.ui``) into the plugin system
("everything is a plugin"), registered through the standard ``basis.plugins``
entry point so it uses the same discovery/lifecycle path as any third-party
plugin.

Component families live directly under the plugin package (each family a
package with its own ``__init__.py``, e.g. ``basis.plugins.ui.button``), and
``basis.plugins.ui.theme`` holds ``ThemeStore`` / ``ThemeProvider``.

Importing this package binds the canonical ``plugin`` instance (entry-point
convention) but does NOT import the component families: like the former
``basis.ui`` package, custom elements register only when an app imports the
component modules it actually uses (e.g. ``import basis.plugins.ui.button.button``).
"""

from basis.plugins.ui.plugin import UiPlugin, plugin as ui_plugin

# The canonical module-level ``plugin`` variable (entry-point convention).
# Re-exposed explicitly: importing the package also binds the submodule
# ``basis.plugins.ui.plugin`` as a package attribute, which would shadow this
# otherwise (entry points must resolve the instance, not the submodule).
plugin = ui_plugin

__all__ = ["UiPlugin", "plugin", "ui_plugin"]
